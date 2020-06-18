import itertools
import math
import os

import numpy as np
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from django.db.models import F, Q
from django.db.utils import ProgrammingError
from django.dispatch import receiver
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_pandas.io import read_frame
from simple_history.signals import post_create_historical_record

from .models import *

agv_list = [1]
robot_list = [1, 2]

send_cmd_hold = {}
x_check = {}
y_check = {}
for i in agv_list:
    send_cmd_hold[i] = 0
    x_check[i] = 999.9
    y_check[i] = 999.9

db_update_list = []
db_update_initial = True

# Home Location #
home_col = 48
home_row = 9


logfilename = 'serverlog.txt'


def logfile_update(filename, lines_to_append):
    if not os.path.exists(filename):
        with open(filename, 'w') as file_object:
            pass

    with open(filename, 'r') as file_object:
        lines = file_object.readlines()

    line_limit = 33
    if len(lines) >= line_limit:
        with open(filename, 'w') as file_object:
            for pos, line in enumerate(lines):
                if pos > len(lines) - line_limit:
                    file_object.write(line)

    if not isinstance(lines_to_append, (list, tuple)):
        lines_to_append = [lines_to_append]

    with open(filename, 'a+') as file_object:
        appendEOL = False
        # Move read cursor to the start of file.
        file_object.seek(0)
        # Check if file is not empty
        data = file_object.read(100)
        if len(data) > 0:
            appendEOL = True
        # Iterate over each string in the list
        for line in lines_to_append:
            # If file is not empty then append '\n' before first line for
            # other lines always append '\n' before appending line
            if appendEOL == True:
                file_object.write('\n')
            else:
                appendEOL = True
            # Append element at the end of file
            file_object.write(line)


def datetime_now():
    return timezone.localtime().strftime('%Y-%m-%d %H:%M:%S   ')


def initial():
    try:
        # Create buffer sql variable for communication
        for agv_no in agv_list:
            if not AgvTransfer.objects.filter(id=agv_no).exists():
                qs_transfer = AgvTransfer(id=agv_no)
                qs_transfer.save()

        for robot_no in robot_list:
            if not RobotStatus.objects.filter(robot_no=robot_no).exists():
                qs_robot = RobotStatus(robot_no=robot_no)
                qs_robot.save()

        # Clear old log for not important data
        days_history_keep = 30
        date_keep = timezone.now() - timezone.timedelta(days=days_history_keep)

        Storage.history.filter(history_date__lt=date_keep).delete()
        AgvProductionPlan.history.filter(history_date__lt=date_keep).delete()
        RobotQueue.history.filter(history_date__lt=date_keep).delete()
        AgvQueue.history.filter(history_date__lt=date_keep).delete()
        AgvTransfer.history.filter(history_date__lt=date_keep).delete()

        # Clear old log for important data
        years_history_keep = 5
        date_keep = timezone.now() - timezone.timedelta(days=round(365.2422 * years_history_keep, 0))

        Product.history.filter(history_date__lt=date_keep).delete()

        # Clear error product log
        Product.history.filter(qty_storage__isnull=True).delete()

        # Create setting sql variable for keep setting
        if not Setting.objects.filter(id=1).exists():
            qs_setting = Setting(id=1)
            qs_setting.save()

    except ProgrammingError:
        print('initial_data error')


def robot_check():
    try:
        qs_robot = RobotQueue.objects.filter(updated=1)
        if qs_robot:
            qs_plan = AgvProductionPlan.objects.all()
            if qs_plan:

                class Found(Exception):
                    pass

                try:
                    scheduler.pause_job(job_id='robot_check')
                    for i in qs_plan.select_related('product_name'):
                        for j in qs_robot:
                            if i.product_name.product_name == j.product_id.product_name.product_name:
                                raise Found
                except Found:
                    obj_plan = i
                    obj_robot = j

                    # Only store to pre-assigned storage and don't have any inventory before it
                    qs_avail_storage = Storage.objects.filter(storage_for=obj_plan.product_name.product_name)
                    qs_occupied = qs_avail_storage.filter(Q(have_inventory=True) | Q(storage_id__in=AgvQueue.objects.all().values('place_id')))
                    for column_id in qs_occupied.order_by().distinct().values_list('column_id', flat=True):
                        occupied_outer = qs_occupied.filter(column_id=column_id).order_by('row').last()
                        if occupied_outer:
                            qs_avail_storage = qs_avail_storage.exclude(column_id=column_id, row__lte=occupied_outer.row)

                    avail_storage_zone_a = qs_avail_storage.filter(zone='A').order_by('area', 'col', 'row')
                    avail_storage_zone_b = qs_avail_storage.filter(zone='B').order_by('-area', '-col', 'row')
                    pk_avail_storage_list = list(avail_storage_zone_a.values_list('storage_id', flat=True)) + list(avail_storage_zone_b.values_list('storage_id', flat=True))
                    if pk_avail_storage_list:
                        # Find last storage column for obj_to
                        column_zone_a = Storage.objects.filter(storage_for=obj_plan.product_name.product_name, zone='A').order_by('area', 'col')
                        column_zone_b = Storage.objects.filter(storage_for=obj_plan.product_name.product_name, zone='B').order_by('-area', '-col')
                        column_id_list = list(column_zone_a.distinct().values_list('column_id', flat=True)) + list(column_zone_b.distinct().values_list('column_id', flat=True))
                        df_created_on = pd.DataFrame(columns=['column_id', 'created_on']).set_index('column_id')
                        for column_id in column_id_list:
                            qs_last_inventory_in_column = Storage.objects.filter(column_id=column_id, have_inventory=True)
                            if qs_last_inventory_in_column.exists():
                                last_inventory_in_column = qs_last_inventory_in_column.order_by('-row')[0]
                                df_created_on.loc[column_id] = [last_inventory_in_column.created_on]
                        if len(df_created_on) > 0:
                            last_column_id = list(df_created_on.sort_values(by=['created_on'], ascending=False).index)[0]
                            last_column_id_index = column_id_list.index(last_column_id)
                            column_id_list = column_id_list[last_column_id_index:] + column_id_list[:last_column_id_index]
                            for column_id in column_id_list:
                                if Storage.objects.filter(storage_id__in=pk_avail_storage_list, column_id=column_id).exists():
                                    obj_to = Storage.objects.filter(storage_id__in=pk_avail_storage_list, column_id=column_id).order_by('row').first()
                                    break
                                # Find next available column for obj_to if last storage column is full
                        else:
                            obj_to = Storage.objects.filter(storage_id=pk_avail_storage_list[0]).first()

                        obj_queue = AgvQueue()
                        obj_queue.product_name = obj_plan.product_name
                        obj_queue.lot_name = obj_plan.lot_name
                        obj_queue.qty_act = obj_robot.qty_act
                        obj_queue.created_on = timezone.now()
                        obj_queue.robot_no = obj_robot.robot_no
                        obj_queue.pick_id = None
                        obj_queue.place_id = obj_to
                        obj_queue.mode = 1
                        obj_queue.changeReason = 'New AGV Queue'
                        obj_queue.save()

                        obj_robot.changeReason = 'Update Robot Queue (Move to transfer)'
                        obj_robot.delete()

                        obj_plan.qty_remain = obj_plan.qty_remain - obj_robot.qty_act
                        if int(obj_plan.qty_remain) <= 0:
                            obj_plan.qty_remain = 0
                            obj_plan.changeReason = 'Finish Production Plan'
                            obj_plan.delete()
                        else:
                            obj_plan.changeReason = 'Update Production Plan (Move to queue)'
                            obj_plan.save()
                finally:
                    scheduler.resume_job(job_id='robot_check')
    except ProgrammingError:
        print('robot_check error')


def transfer_check():
    global x_check, y_check

    try:
        qs_transfer_list = []
        for agv_no in agv_list:
            qs_transfer = AgvTransfer.objects.filter(id=agv_no)
            if qs_transfer.exists():
                qs_transfer_list.append(qs_transfer)

        for agv_no, qs_transfer in enumerate(qs_transfer_list, 1):
            obj_transfer = get_object_or_404(qs_transfer)

            agv_x, agv_y, agv_beta = transfer_adjust(obj_transfer)
            agv_col, agv_row = position_cal(agv_x, agv_y)
            if (agv_beta >= 0 and agv_beta < 45) or (agv_beta >= 315 and agv_beta < 360):
                agv_direction = 'L'
            elif agv_beta >= 45 and agv_beta < 135:
                agv_direction = 'B'
            elif agv_beta >= 135 and agv_beta < 225:
                agv_direction = 'R'
            elif agv_beta >= 225 and agv_beta < 315:
                agv_direction = 'T'

            # Update AgvTransfer database
            obj_transfer.agv_col = agv_col
            obj_transfer.agv_row = agv_row
            obj_transfer.agv_direction = agv_direction
            obj_transfer.save_without_historical_record(update_fields=['agv_col', 'agv_row', 'agv_direction'])

            if obj_transfer.run == 1 and obj_transfer.status == 0 and send_cmd_hold[agv_no] == 0:
                qs_queue = AgvQueue.objects.filter(Q(agv_no=agv_no) | Q(agv_no__isnull=True))
                if len(qs_queue) >= 1:
                    if len(qs_queue.filter(agv_no=agv_no)) >= 1:
                        qs_queue = qs_queue.filter(agv_no=agv_no)[:1]
                    else:
                        qs_queue = qs_queue.filter(agv_no__isnull=True)[:1]
                        obj_queue = qs_queue.first()
                        obj_queue.agv_no = agv_no
                        obj_queue.save()
                    scheduler.add_job(agv_route, 'date', run_date=timezone.now(), args=[agv_no, qs_transfer, qs_queue], id='agv_route_{}'.format(agv_no), replace_existing=True)
            elif obj_transfer.run == 0:
                x_check[agv_no] = y_check[agv_no] = 999.9
                job_id_list = ['agv_route_{}'.format(agv_no), 'transfer_update_{}'.format(agv_no), 'send_cmd_reset_hold_{}'.format(agv_no)]
                for job_id in job_id_list:
                    if scheduler.get_job(job_id=job_id) is not None:
                        scheduler.remove_job(job_id=job_id)

    except ProgrammingError:
        print('transfer_check error')


def transfer_adjust(obj_transfer):
    beta_offset = 2.505388716
    agv_beta = obj_transfer.beta_nav - beta_offset
    if agv_beta < 0:
        agv_beta = agv_beta + 360.0
    # Offset NAV from center of rotation
    nav_offset = 0.5
    agv_x = obj_transfer.x_nav - (nav_offset * np.cos(agv_beta * np.pi / 180.0))
    agv_y = obj_transfer.y_nav - (nav_offset * np.sin(agv_beta * np.pi / 180.0))
    return agv_x, agv_y, agv_beta


def transfer_update(agv_no):
    qs_transfer = AgvTransfer.objects.filter(id=agv_no)
    obj_transfer = get_object_or_404(qs_transfer)

    obj_transfer.status = 1
    obj_transfer.changeReason = 'Delayed AGV Command'
    obj_transfer.save(update_fields=['status'])
    # Block transfer check for 10 sec, to prevent error from communication
    scheduler.add_job(send_cmd_reset_hold, 'date', run_date=timezone.now() + timezone.timedelta(seconds=10), args=[agv_no], id='send_cmd_reset_hold_{}'.format(agv_no), replace_existing=True)
    # print(datetime_now() + 'Send New Command to AGV #{}'.format(agv_no))
    logfile_update(logfilename, datetime_now() + 'Send New Command to AGV #{}'.format(agv_no))


def send_cmd_reset_hold(agv_no):
    global send_cmd_hold
    send_cmd_hold[agv_no] = 0


def agv_route(agv_no, qs_transfer, qs_queue):
    global send_cmd_hold, x_check, y_check, home_col, home_row

    scheduler.pause_job(job_id='transfer_check')

    obj_transfer = get_object_or_404(qs_transfer)
    agv_x, agv_y, agv_beta = transfer_adjust(obj_transfer)

    # Calculate Route
    # Pattern 0: ArmRun -> Rev
    # Pattern 1: Rev -> ArmRun
    # Pattern 2: ArmPrepare -> FW -> Pick(Robot)
    # Pattern 3: ArmPrepare -> FW -> Pick(Storage)
    # Pattern 4: FW -> ArmPut
    # Reverse NAV Offset 1.14m
    # Forward NAV Offset 0.60m + dist_Offset (Pattern 3,4)

    # Step for storage
    # 1: Runway Stock/Home to Runway Robot (Pattern 0)
    # 2: Runway Robot to Robot (Pattern 2)
    # 3: Robot to Runway Robot (Pattern 1)
    # 4: Runway Robot to Runway Stock (Pattern 0)
    # 5: Runway Stock to Stock (Pattern 4)
    # 6: Stock to Runway Stock (Pattern 1)
    # 7: Runway Stock to Home (If no task queue) (Pattern 1, 4)

    df_queue = read_frame(qs_queue, index_col='id', verbose=False)
    if len(df_queue) >= 1 and send_cmd_hold[agv_no] == 0:
        active_queue = df_queue.iloc[0]
        # print('\n' + datetime_now() + 'Mode={} Step={}'.format(active_queue['mode'], obj_transfer.step))
        logfile_update(logfilename, '\n' + datetime_now() + 'Mode={} Step={}'.format(active_queue['mode'], obj_transfer.step))

        robot_row = 6
        runway_row = 9

        # Check Distance
        dist_check = 2.5
        dist_error = np.sqrt((agv_x - x_check[agv_no]) ** 2 + (agv_y - y_check[agv_no]) ** 2)

        # Check AGV col, row
        agv_col, agv_row = position_cal(agv_x, agv_y)

        if obj_transfer.step == 1:
            if active_queue['mode'] == 1:
                target_col = 45 if active_queue['robot_no'] == 1 else 40
                target_row = runway_row
                if dist_error > dist_check:
                    route_calculate(agv_no, obj_transfer, 0, agv_x, agv_y, target_col, target_row)
                else:
                    agv_next_step(agv_no, obj_transfer, agv_x, agv_y, dist_error, agv_col, agv_row)
            elif active_queue['mode'] == 2:
                target_col = active_queue['pick_col']
                target_row = runway_row
                if dist_error > dist_check:
                    route_calculate(agv_no, obj_transfer, 0, agv_x, agv_y, target_col, target_row)
                else:
                    agv_next_step(agv_no, obj_transfer, agv_x, agv_y, dist_error, agv_col, agv_row)
        elif obj_transfer.step == 2:
            if active_queue['mode'] == 1:
                target_col = 45 if active_queue['robot_no'] == 1 else 40
                target_row = robot_row
                if dist_error > (dist_check + 3.0):
                    obj_coor = get_object_or_404(Coordinate, layout_col=target_col, layout_row=runway_row)
                    col_offset = 1 if (agv_x < obj_coor.coor_x) else -1
                    obj_coor = get_object_or_404(Coordinate, layout_col=target_col + col_offset, layout_row=runway_row)
                    fix_x = obj_coor.coor_x
                    fix_y = obj_coor.coor_y
                    route_calculate(agv_no, obj_transfer, 2, fix_x, fix_y, target_col, target_row)
                else:
                    agv_next_step(agv_no, obj_transfer, agv_x, agv_y, dist_error, agv_col, agv_row)
            elif active_queue['mode'] == 2:
                target_col = active_queue['pick_col']
                target_row = active_queue['pick_row']
                if dist_error > (dist_check + 3.0):
                    obj_coor = get_object_or_404(Coordinate, layout_col=target_col, layout_row=runway_row)
                    col_offset = 1 if (agv_x < obj_coor.coor_x) else -1
                    obj_coor = get_object_or_404(Coordinate, layout_col=target_col + col_offset, layout_row=runway_row)
                    fix_x = obj_coor.coor_x
                    fix_y = obj_coor.coor_y
                    route_calculate(agv_no, obj_transfer, 3, fix_x, fix_y, target_col, target_row)
                else:
                    agv_next_step(agv_no, obj_transfer, agv_x, agv_y, dist_error, agv_col, agv_row)
        elif obj_transfer.step == 3:
            if active_queue['mode'] == 1:
                target_col = 45 if active_queue['robot_no'] == 1 else 40
                target_row = runway_row
                if dist_error > dist_check:
                    obj_coor = get_object_or_404(Coordinate, layout_col=target_col, layout_row=robot_row)
                    fix_x = obj_coor.coor_x
                    fix_y = obj_coor.coor_y
                    route_calculate(agv_no, obj_transfer, 1, fix_x, fix_y, target_col, target_row)
                else:
                    agv_next_step(agv_no, obj_transfer, agv_x, agv_y, dist_error, agv_col, agv_row)
            elif active_queue['mode'] == 2:
                target_col = active_queue['pick_col']
                target_row = runway_row
                if dist_error > dist_check:
                    obj_coor = get_object_or_404(Coordinate, layout_col=target_col, layout_row=active_queue['pick_row'])
                    fix_x = obj_coor.coor_x
                    fix_y = obj_coor.coor_y
                    route_calculate(agv_no, obj_transfer, 1, fix_x, fix_y, target_col, target_row)
                else:
                    agv_next_step(agv_no, obj_transfer, agv_x, agv_y, dist_error, agv_col, agv_row)
        elif obj_transfer.step == 4:
            target_col = active_queue['place_col']
            target_row = runway_row
            if dist_error > dist_check:
                route_calculate(agv_no, obj_transfer, 0, agv_x, agv_y, target_col, target_row)
            else:
                agv_next_step(agv_no, obj_transfer, agv_x, agv_y, dist_error, agv_col, agv_row)
        elif obj_transfer.step == 5:
            target_col = active_queue['place_col']
            target_row = active_queue['place_row']
            if dist_error > dist_check:
                obj_coor = get_object_or_404(Coordinate, layout_col=target_col, layout_row=runway_row)
                col_offset = 1 if (agv_x < obj_coor.coor_x) else -1
                obj_coor = get_object_or_404(Coordinate, layout_col=target_col + col_offset, layout_row=runway_row)
                fix_x = obj_coor.coor_x
                fix_y = obj_coor.coor_y
                route_calculate(agv_no, obj_transfer, 4, fix_x, fix_y, target_col, target_row)
            else:
                agv_next_step(agv_no, obj_transfer, agv_x, agv_y, dist_error, agv_col, agv_row)
        elif obj_transfer.step == 6:
            target_col = active_queue['place_col']
            if active_queue['place_row'] > runway_row:
                target_row = runway_row + 1 if active_queue['place_row'] - 2 > runway_row else runway_row
            elif active_queue['place_row'] < runway_row:
                target_row = runway_row - 1 if active_queue['place_row'] + 2 < runway_row else runway_row
            if dist_error > dist_check:
                obj_coor = get_object_or_404(Coordinate, layout_col=target_col, layout_row=active_queue['place_row'])
                fix_x = obj_coor.coor_x
                fix_y = obj_coor.coor_y
                route_calculate(agv_no, obj_transfer, 1, fix_x, fix_y, target_col, target_row)
            else:
                # print(datetime_now() + 'Finish, NAV {:.2f},{:.2f} Check {:.2f},{:.2f} Error {:.4f}'.format(agv_x, agv_y, x_check[agv_no], y_check[agv_no], dist_error))
                logfile_update(logfilename, datetime_now() + 'Finish, NAV {:.2f},{:.2f} Check {:.2f},{:.2f} Error {:.4f}'.format(agv_x, agv_y, x_check[agv_no], y_check[agv_no], dist_error))
                x_check[agv_no] = y_check[agv_no] = 999.9
                if target_row == runway_row:
                    obj_transfer.step = obj_transfer.step + 1
                    obj_transfer = reset_route(obj_transfer, agv_col, agv_row)
                    obj_transfer.changeReason = 'Next Step'
                    obj_transfer.save(update_fields=['qty', 'x1', 'y1', 'x2', 'y2', 'x3', 'y3', 'x4', 'y4', 'x5', 'y5', 'col1', 'row1', 'col2', 'row2', 'col3', 'row3', 'col4', 'row4', 'col5', 'row5', 'step'])
                else:
                    # print(datetime_now() + 'Finish Order')
                    logfile_update(logfilename, datetime_now() + 'Finish Order')
                    obj_transfer.step = 1
                    obj_transfer = reset_route(obj_transfer, agv_col, agv_row)
                    obj_transfer.changeReason = 'Finish Order'
                    obj_transfer.save(update_fields=['qty', 'x1', 'y1', 'x2', 'y2', 'x3', 'y3', 'x4', 'y4', 'x5', 'y5', 'col1', 'row1', 'col2', 'row2', 'col3', 'row3', 'col4', 'row4', 'col5', 'row5', 'step'])

                    if active_queue['mode'] == 1:
                        obj_storage = get_object_or_404(Storage, storage_id=active_queue['place_id'])
                        obj_storage.inv_product = get_object_or_404(Product, product_name=active_queue['product_name'])
                        obj_storage.inv_qty = active_queue['qty_act']
                        obj_storage.lot_name = active_queue['lot_name']
                        obj_storage.created_on = active_queue['created_on']
                        obj_storage.updated_on = timezone.now()
                        obj_storage.changeReason = 'New inventory (Storage Order)'
                        obj_storage.save()

                        obj_queue = get_object_or_404(qs_queue)
                        obj_queue.changeReason = 'Finish AGV Queue'
                        obj_queue.delete()

                        dt = timezone.localtime()
                        year, month, day = dt.year, dt.month, dt.day
                        if 0 <= dt.hour < 8:
                            shift = 1
                        elif 8 <= dt.hour < 16:
                            shift = 2
                        elif 16 <= dt.hour < 24:
                            shift = 3
                        obj_report, created = Report.objects.get_or_create(product=obj_storage.inv_product, year=year, month=month, day=day, shift=shift)
                        obj_report.qty_produce += obj_storage.inv_qty
                        obj_report.save()
                    elif active_queue['mode'] == 2:
                        obj_storage = get_object_or_404(Storage, storage_id=active_queue['pick_id'])
                        obj_storage.inv_product = None
                        obj_storage.inv_qty = None
                        obj_storage.lot_name = None
                        obj_storage.created_on = None
                        obj_storage.updated_on = timezone.now()
                        obj_storage.changeReason = 'Remove inventory (Retrieve/Move Order)'
                        obj_storage.save()

                        obj_storage = get_object_or_404(Storage, storage_id=active_queue['place_id'])
                        obj_storage.inv_product = get_object_or_404(Product, product_name=active_queue['product_name'])
                        obj_storage.inv_qty = active_queue['qty_act']
                        obj_storage.lot_name = active_queue['lot_name']
                        obj_storage.created_on = active_queue['created_on']
                        obj_storage.updated_on = timezone.now()
                        obj_storage.changeReason = 'New inventory (Retrieve/Move Order)'
                        obj_storage.save()

                        obj_queue = get_object_or_404(qs_queue)
                        obj_queue.changeReason = 'Finish AGV Queue'
                        obj_queue.delete()

                        if not obj_storage.is_inventory:
                            dt = timezone.localtime()
                            year, month, day = dt.year, dt.month, dt.day
                            if 0 <= dt.hour < 8:
                                shift = 1
                            elif 8 <= dt.hour < 16:
                                shift = 2
                            elif 16 <= dt.hour < 24:
                                shift = 3
                            obj_report, created = Report.objects.get_or_create(product=obj_storage.inv_product, year=year, month=month, day=day, shift=shift)
                            obj_report.qty_sale += obj_storage.inv_qty
                            obj_report.save()

        elif obj_transfer.step == 7:
            target_col = home_col
            target_row = home_row
            if dist_error > dist_check:
                route_calculate(agv_no, obj_transfer, 0, agv_x, agv_y, target_col, target_row)
            else:
                # print(datetime_now() + 'Finish, NAV {:.2f},{:.2f} Check {:.2f},{:.2f} Error {:.4f}'.format(agv_x, agv_y, x_check[agv_no], y_check[agv_no], dist_error))
                logfile_update(logfilename, datetime_now() + 'Finish, NAV {:.2f},{:.2f} Check {:.2f},{:.2f} Error {:.4f}'.format(agv_x, agv_y, x_check[agv_no], y_check[agv_no], dist_error))
                # print(datetime_now() + 'Finish Order')
                logfile_update(logfilename, datetime_now() + 'Finish Order')
                x_check[agv_no] = y_check[agv_no] = 999.9
                obj_transfer.step = 1
                obj_transfer = reset_route(obj_transfer, agv_col, agv_row)
                obj_transfer.changeReason = 'Finish Order'
                obj_transfer.save(update_fields=['qty', 'x1', 'y1', 'x2', 'y2', 'x3', 'y3', 'x4', 'y4', 'x5', 'y5', 'col1', 'row1', 'col2', 'row2', 'col3', 'row3', 'col4', 'row4', 'col5', 'row5', 'step'])

                if active_queue['mode'] == 1:
                    obj_storage = get_object_or_404(Storage, storage_id=active_queue['place_id'])
                    obj_storage.inv_product = get_object_or_404(Product, product_name=active_queue['product_name'])
                    obj_storage.inv_qty = active_queue['qty_act']
                    obj_storage.lot_name = active_queue['lot_name']
                    obj_storage.created_on = active_queue['created_on']
                    obj_storage.updated_on = timezone.now()
                    obj_storage.changeReason = 'New inventory (Storage Order)'
                    obj_storage.save()

                    obj_queue = get_object_or_404(qs_queue)
                    obj_queue.changeReason = 'Finish AGV Queue'
                    obj_queue.delete()
                elif active_queue['mode'] == 2:
                    obj_storage = get_object_or_404(Storage, storage_id=active_queue['place_id'])
                    obj_storage.inv_product = get_object_or_404(Product, product_name=active_queue['product_name'])
                    obj_storage.inv_qty = active_queue['qty_act']
                    obj_storage.lot_name = active_queue['lot_name']
                    obj_storage.created_on = active_queue['created_on']
                    obj_storage.updated_on = timezone.now()
                    obj_storage.changeReason = 'New inventory (Retrieve/Move Order)'
                    obj_storage.save()

                    obj_storage = get_object_or_404(Storage, storage_id=active_queue['pick_id'])
                    obj_storage.inv_product = None
                    obj_storage.inv_qty = None
                    obj_storage.lot_name = None
                    obj_storage.created_on = None
                    obj_storage.updated_on = timezone.now()
                    obj_storage.changeReason = 'Remove inventory (Retrieve/Move Order)'
                    obj_storage.save()

                    obj_queue = get_object_or_404(qs_queue)
                    obj_queue.changeReason = 'Finish AGV Queue'
                    obj_queue.delete()

                    if not obj_storage.is_inventory:
                        dt = timezone.localtime()
                        year, month, day = dt.year, dt.month, dt.day
                        if 0 <= dt.hour < 8:
                            shift = 1
                        elif 8 <= dt.hour < 16:
                            shift = 2
                        elif 16 <= dt.hour < 24:
                            shift = 3
                        obj_report, created = Report.objects.get_or_create(product=obj_storage.inv_product, year=year, month=month, day=day, shift=shift)
                        obj_report.qty_sale += obj_storage.inv_qty
                        obj_report.save()
        else:
            # print('Step Error, Reset To Step 1')
            logfile_update(logfilename, 'Step Error, Reset To Step 1')
            obj_transfer.step = 1
            obj_transfer = reset_route(obj_transfer, agv_col, agv_row)
            obj_transfer.changeReason = 'Step Error, Reset To Step 1'
            obj_transfer.save(update_fields=['qty', 'x1', 'y1', 'x2', 'y2', 'x3', 'y3', 'x4', 'y4', 'x5', 'y5', 'col1', 'row1', 'col2', 'row2', 'col3', 'row3', 'col4', 'row4', 'col5', 'row5', 'step'])

    scheduler.resume_job(job_id='transfer_check')


def agv_next_step(agv_no, obj_transfer, agv_x, agv_y, dist_error, agv_col, agv_row):
    # print(datetime_now() + 'Finish, NAV {:.2f},{:.2f} Check {:.2f},{:.2f} Error {:.4f}'.format(agv_x, agv_y, x_check[agv_no], y_check[agv_no], dist_error))
    logfile_update(logfilename, datetime_now() + 'Finish, NAV {:.2f},{:.2f} Check {:.2f},{:.2f} Error {:.4f}'.format(agv_x, agv_y, x_check[agv_no], y_check[agv_no], dist_error))
    x_check[agv_no] = y_check[agv_no] = 999.9
    obj_transfer.step = obj_transfer.step + 1
    obj_transfer = reset_route(obj_transfer, agv_col, agv_row)
    obj_transfer.changeReason = 'Next Step'
    obj_transfer.save(update_fields=['qty', 'x1', 'y1', 'x2', 'y2', 'x3', 'y3', 'x4', 'y4', 'x5', 'y5', 'col1', 'row1', 'col2', 'row2', 'col3', 'row3', 'col4', 'row4', 'col5', 'row5', 'step'])


def reset_route(obj_transfer, agv_col, agv_row):
    obj_transfer.qty = 0
    obj_transfer.x1 = obj_transfer.x_nav
    obj_transfer.y1 = obj_transfer.y_nav
    obj_transfer.x2 = obj_transfer.x3 = obj_transfer.x4 = obj_transfer.x5 = 0
    obj_transfer.y2 = obj_transfer.y3 = obj_transfer.y4 = obj_transfer.y5 = 0
    obj_transfer.col1 = agv_col
    obj_transfer.row1 = agv_row
    obj_transfer.col2 = obj_transfer.col3 = obj_transfer.col4 = obj_transfer.col5 = 0
    obj_transfer.row2 = obj_transfer.row3 = obj_transfer.row4 = obj_transfer.row5 = 0
    return obj_transfer


def agv_route_home(agv_no, qs_transfer):
    global x_check, y_check, home_col, home_row

    scheduler.pause_job(job_id='transfer_check')

    obj_transfer = get_object_or_404(qs_transfer)
    pattern = 1.0
    agv_x, agv_y, agv_beta = transfer_adjust(obj_transfer)
    agv_col, agv_row = position_cal(agv_x, agv_y)
    target_col = home_col
    target_row = home_row

    if agv_row != target_row or agv_col != target_col:
        route_calculate(agv_no, obj_transfer, pattern, agv_x, agv_y, target_col, target_row)

        obj_transfer = get_object_or_404(qs_transfer)
        x_check[agv_no] = y_check[agv_no] = 999.9
        obj_transfer.step = 1
        obj_transfer.changeReason = 'Manual Update AGV Transfer'
        obj_transfer.save(update_fields=['qty', 'x1', 'y1', 'x2', 'y2', 'x3', 'y3', 'x4', 'y4', 'x5', 'y5', 'col1', 'row1', 'col2', 'row2', 'col3', 'row3', 'col4', 'row4', 'col5', 'row5', 'step'])

    scheduler.resume_job(job_id='transfer_check')


def agv_route_manual(agv_no, qs_transfer, pattern, target_col, target_row):
    global x_check, y_check

    scheduler.pause_job(job_id='transfer_check')

    obj_transfer = get_object_or_404(qs_transfer)
    agv_x, agv_y, agv_beta = transfer_adjust(obj_transfer)

    route_calculate(agv_no, obj_transfer, pattern, agv_x, agv_y, target_col, target_row)

    obj_transfer = get_object_or_404(qs_transfer)
    x_check[agv_no] = y_check[agv_no] = 999.9
    obj_transfer.step = 1
    obj_transfer.changeReason = 'Manual Update AGV Transfer'
    obj_transfer.save(update_fields=['step'])

    scheduler.resume_job(job_id='transfer_check')


def position_cal(agv_x, agv_y):
    df_coordinate = read_frame(Coordinate.objects.all(), index_col='coor_id', verbose=False)
    df_coordinate['dist'] = np.sqrt((agv_x - df_coordinate['coor_x']) ** 2 + (agv_y - df_coordinate['coor_y']) ** 2)
    try:
        index = df_coordinate.nsmallest(1, 'dist', keep='first').index.values
        agv_col, agv_row, x, y, dist = df_coordinate.loc[index].to_numpy().flatten()
        return agv_col, agv_row
    except TypeError:
        return None, None


def dist_compensate(x1, y1, x2, y2, dist_offset):
    theta = None
    dx = x2 - x1
    dy = y2 - y1
    dist = np.sqrt(dx ** 2 + dy ** 2)
    if dx != 0:
        theta = np.arctan(dy / dx)
    elif dx == 0 and dy >= 0:
        theta = np.pi / 2
    elif dx == 0 and dy < 0:
        theta = 3 * np.pi / 2
    if dx >= 0 and dy >= 0:
        theta = theta
    elif dx < 0 and dy >= 0:
        theta = theta + np.pi
    elif dx < 0 and dy < 0:
        theta = theta + np.pi
    elif dx >= 0 and dy < 0:
        theta = theta + 2 * np.pi
    x_offset = x1 + (dist + dist_offset) * np.cos(theta)
    y_offset = y1 + (dist + dist_offset) * np.sin(theta)
    return x_offset, y_offset


def route_calculate(agv_no, obj_transfer, pattern, agv_x, agv_y, target_col, target_row):
    global send_cmd_hold, x_check, y_check

    # print(datetime_now() + 'Recalculate Route for AGV #{}'.format(agv_no))
    logfile_update(logfilename, datetime_now() + 'Recalculate Route for AGV #{}'.format(agv_no))
    agv_col, agv_row = position_cal(agv_x, agv_y)
    if agv_col == target_col and agv_row == target_row:
        obj_coor = get_object_or_404(Coordinate, layout_col=agv_col, layout_row=agv_row)
        x_check[agv_no] = obj_coor.coor_x
        y_check[agv_no] = obj_coor.coor_y
    else:
        runway_row = 9

        # Calculate Route Coordinate
        df_route = pd.DataFrame()
        new_coor = read_frame(Coordinate.objects.filter(layout_col=agv_col, layout_row=agv_row), index_col='coor_id', verbose=False)
        df_route = df_route.append(new_coor)

        while (agv_col != target_col) or (agv_row != target_row):
            if agv_col != target_col and agv_row != runway_row:
                new_coor = read_frame(Coordinate.objects.filter(layout_col=agv_col, layout_row=runway_row), index_col='coor_id', verbose=False)
                df_route = df_route.append(new_coor)
            elif agv_col != target_col and agv_row == runway_row:
                new_coor = read_frame(Coordinate.objects.filter(layout_col=target_col, layout_row=runway_row), index_col='coor_id', verbose=False)
                df_route = df_route.append(new_coor)
            elif agv_col == target_col:
                new_coor = read_frame(Coordinate.objects.filter(layout_col=target_col, layout_row=target_row), index_col='coor_id', verbose=False)
                df_route = df_route.append(new_coor)
            agv_col, agv_row, x, y = df_route.iloc[-1]

        # Start point offset
        dist_offset_start = 0.1
        df_route.iloc[0, df_route.columns.get_loc('coor_x')], df_route.iloc[0, df_route.columns.get_loc('coor_y')] = dist_compensate(
            df_route['coor_x'].iloc[1], df_route['coor_y'].iloc[1], df_route['coor_x'].iloc[0], df_route['coor_y'].iloc[0], dist_offset_start
        )

        # Pattern 0: ArmRun -> Rev
        # Pattern 1: Rev -> ArmRun
        # Pattern 2: ArmPrepare -> FW -> Pick(Robot)
        # Pattern 3: ArmPrepare -> FW -> Pick(Storage)
        # Pattern 4: FW -> ArmPut
        # Reverse NAV Offset 1.14m
        # Forward NAV Offset 0.60m + dist_Offset (Pattern 3,4)

        # Final point offset
        dist_offset_final = 1.33
        dist_offset = {
            0: dist_offset_final + 1.3,
            1: dist_offset_final - 0.6,
            2: dist_offset_final,
            3: dist_offset_final,
            4: dist_offset_final,
        }

        df_route.iloc[-1, df_route.columns.get_loc('coor_x')], df_route.iloc[-1, df_route.columns.get_loc('coor_y')] = dist_compensate(
            df_route['coor_x'].iloc[-2], df_route['coor_y'].iloc[-2], df_route['coor_x'].iloc[-1], df_route['coor_y'].iloc[-1], dist_offset[pattern]
        )
        df_route.reset_index(drop=True, inplace=True)

        x_check[agv_no], y_check[agv_no] = dist_compensate(df_route['coor_x'].iloc[-2], df_route['coor_y'].iloc[-2], df_route['coor_x'].iloc[-1], df_route['coor_y'].iloc[-1], -dist_offset_final)

        # print(' AGV #{}, Pattern = {}'.format(agv_no, pattern))
        # print(' Target x = {:.4f}, y = {:.4f}'.format(x_check[agv_no], y_check[agv_no]))
        # print(df_route.to_string(index=False))
        logfile_update(logfilename, [' AGV #{}, Pattern = {}'.format(agv_no, pattern), ' Target x = {:.4f}, y = {:.4f}'.format(x_check[agv_no], y_check[agv_no]), df_route.to_string(index=False)])

        obj_transfer.pattern = float(pattern)
        obj_transfer.qty = float(len(df_route))
        obj_transfer.x1 = df_route['coor_x'].iloc[0] if len(df_route) > 0 else 0
        obj_transfer.x2 = df_route['coor_x'].iloc[1] if len(df_route) > 1 else 0
        obj_transfer.x3 = df_route['coor_x'].iloc[2] if len(df_route) > 2 else 0
        obj_transfer.x4 = df_route['coor_x'].iloc[3] if len(df_route) > 3 else 0
        obj_transfer.x5 = df_route['coor_x'].iloc[4] if len(df_route) > 4 else 0
        obj_transfer.y1 = df_route['coor_y'].iloc[0] if len(df_route) > 0 else 0
        obj_transfer.y2 = df_route['coor_y'].iloc[1] if len(df_route) > 1 else 0
        obj_transfer.y3 = df_route['coor_y'].iloc[2] if len(df_route) > 2 else 0
        obj_transfer.y4 = df_route['coor_y'].iloc[3] if len(df_route) > 3 else 0
        obj_transfer.y5 = df_route['coor_y'].iloc[4] if len(df_route) > 4 else 0
        obj_transfer.col1 = df_route['layout_col'].iloc[0] if len(df_route) > 0 else 0
        obj_transfer.col2 = df_route['layout_col'].iloc[1] if len(df_route) > 1 else 0
        obj_transfer.col3 = df_route['layout_col'].iloc[2] if len(df_route) > 2 else 0
        obj_transfer.col4 = df_route['layout_col'].iloc[3] if len(df_route) > 3 else 0
        obj_transfer.col5 = df_route['layout_col'].iloc[4] if len(df_route) > 4 else 0
        obj_transfer.row1 = df_route['layout_row'].iloc[0] if len(df_route) > 0 else 0
        obj_transfer.row2 = df_route['layout_row'].iloc[1] if len(df_route) > 1 else 0
        obj_transfer.row3 = df_route['layout_row'].iloc[2] if len(df_route) > 2 else 0
        obj_transfer.row4 = df_route['layout_row'].iloc[3] if len(df_route) > 3 else 0
        obj_transfer.row5 = df_route['layout_row'].iloc[4] if len(df_route) > 4 else 0
        obj_transfer.changeReason = 'AGV Update Pattern and Coordinate'
        obj_transfer.save(update_fields=['pattern', 'qty', 'x1', 'y1', 'x2', 'y2', 'x3', 'y3', 'x4', 'y4', 'x5', 'y5', 'col1', 'row1', 'col2', 'row2', 'col3', 'row3', 'col4', 'row4', 'col5', 'row5'])
        send_cmd_hold[agv_no] = 1
        scheduler.add_job(transfer_update, 'date', run_date=timezone.now() + timezone.timedelta(seconds=2), args=[agv_no], id='transfer_update_{}'.format(agv_no), replace_existing=True)


def update_product_db():
    global db_update_list, db_update_initial
    if len(db_update_list) > 0:
        for product_name in db_update_list:
            qs_product = Product.objects.filter(product_name=product_name)
            if qs_product.exists():
                obj = get_object_or_404(qs_product)

                storage_count = Storage.objects.filter(storage_for=obj.product_name).count()
                obj.qty_storage = storage_count * obj.qty_limit

                inv = Storage.objects.filter(storage_for=obj.product_name, inv_product=obj.product_name).aggregate(models.Sum('inv_qty'))['inv_qty__sum']
                obj.qty_inventory = inv if inv else 0

                buffer = Storage.objects.filter(is_inventory=False, inv_product=obj.product_name).aggregate(models.Sum('inv_qty'))['inv_qty__sum']
                obj.qty_buffer = buffer if buffer else 0

                misplace = Storage.objects.filter(is_inventory=True, inv_product=obj.product_name).exclude(storage_for=obj.product_name).aggregate(models.Sum('inv_qty'))['inv_qty__sum']
                obj.qty_misplace = misplace if misplace else 0

                obj.qty_total = obj.qty_inventory + obj.qty_buffer + obj.qty_misplace

                storage_plan = AgvProductionPlan.objects.filter(product_name__product_name=obj.product_name).aggregate(models.Sum('qty_remain'))['qty_remain__sum']
                storage_plan = storage_plan if storage_plan else 0
                qs_avail_storage = Storage.objects.filter(storage_for=obj.product_name)
                qs_occupied = qs_avail_storage.filter(Q(have_inventory=True) | Q(storage_id__in=AgvQueue.objects.all().values('place_id')))
                for column_id in qs_occupied.order_by().distinct().values_list('column_id', flat=True):
                    occupied_outer = qs_occupied.filter(column_id=column_id).order_by('row').last()
                    if occupied_outer:
                        qs_avail_storage = qs_avail_storage.exclude(column_id=column_id, row__lte=occupied_outer.row)
                obj.qty_storage_avail = (qs_avail_storage.count() * obj.qty_limit) - storage_plan

                qs_avail_inventory = Storage.objects.filter(inv_product=obj.product_name, storage_for=obj.product_name).exclude(storage_id__in=AgvQueue.objects.filter(mode=2).values('pick_id'))
                condition_misplace = ~Q(inv_product=obj.product_name) & Q(storage_for=obj.product_name) & Q(have_inventory=True)
                try:
                    age_criteria = Setting.objects.get(id=1).age_criteria if Setting.objects.filter(id=1).exists() else 0
                except:
                    age_criteria = 0
                condition_new = Q(have_inventory=True) & Q(created_on__gte=timezone.now() - timezone.timedelta(days=age_criteria))
                qs_exclude = Storage.objects.filter(condition_misplace | condition_new)
                for column_id in qs_exclude.order_by().distinct().values_list('column_id', flat=True):
                    exclude_outer = qs_exclude.filter(column_id=column_id).order_by('row').last()
                    if exclude_outer:
                        qs_avail_inventory = qs_avail_inventory.exclude(column_id=column_id, row__lte=exclude_outer.row)
                qty_avail_inventory = qs_avail_inventory.aggregate(models.Sum('inv_qty'))['inv_qty__sum']
                obj.qty_inventory_avail = qty_avail_inventory if qty_avail_inventory else 0

                if db_update_initial:
                    try:
                        obj.save_without_historical_record()
                    except:
                        pass
                else:
                    obj.changeReason = 'Update Quantity'
                    obj.save()

                db_update_list.remove(product_name)
            if len(db_update_list) > 0:
                update_product_db()
            if db_update_initial:
                db_update_initial = False


@receiver(post_create_historical_record, sender=HistoricalStorage, dispatch_uid="post_update_storage_db")
def post_update_storage_db(sender, instance, **kwargs):
    global db_update_list
    new_record = instance.history.first()
    try:
        old_record = new_record.prev_record
    except:
        old_record = None
    if old_record:
        new_obj, old_obj = new_record.instance, old_record.instance
        delta = new_record.diff_against(old_record)
        for change in delta.changes:
            if change.field == 'storage_for':
                if old_obj.is_inventory:
                    if change.old not in db_update_list:
                        db_update_list.append(change.old)
                    elif new_obj.is_inventory:
                        db_update_list.append(change.new)
            elif change.field == 'inv_product':
                if new_obj.inv_product:
                    if new_obj.inv_product.product_name not in db_update_list:
                        db_update_list.append(new_obj.inv_product.product_name)
                try:
                    if old_obj.inv_product:
                        if old_obj.inv_product.product_name not in db_update_list:
                            db_update_list.append(old_obj.inv_product.product_name)
                except Product.DoesNotExist:
                    pass
            elif change.field == 'inv_qty':
                if new_obj.inv_product:
                    if new_obj.inv_product.product_name not in db_update_list:
                        db_update_list.append(new_obj.inv_product.product_name)
            elif change.field == 'created_on':
                if new_obj.inv_product:
                    if new_obj.inv_product.product_name not in db_update_list:
                        db_update_list.append(new_obj.inv_product.product_name)
    else:
        new_obj = new_record.instance
        if new_obj.inv_product:
            if new_obj.inv_product.product_name not in db_update_list:
                db_update_list.append(new_obj.inv_product.product_name)
    scheduler.add_job(update_product_db, 'date', run_date=timezone.now() + timezone.timedelta(seconds=1), id='update_product_db', replace_existing=True)


@receiver(post_create_historical_record, sender=HistoricalAgvProductionPlan, dispatch_uid="post_update_agv_plan")
def post_update_agv_plan(sender, instance, **kwargs):
    global db_update_list
    new_record = instance.history.first()
    new_obj = new_record.instance
    try:
        if new_obj.product_name.product_name not in db_update_list:
            db_update_list.append(new_obj.product_name.product_name)
    except AttributeError:
        pass
    scheduler.add_job(update_product_db, 'date', run_date=timezone.now() + timezone.timedelta(seconds=1), id='update_product_db', replace_existing=True)


@receiver(post_create_historical_record, sender=HistoricalAgvQueue, dispatch_uid="post_update_agv_queue")
def post_update_agv_queue(sender, instance, **kwargs):
    global db_update_list
    new_record = instance.history.first()
    new_obj = new_record.instance
    try:
        if new_obj.product_name.product_name not in db_update_list:
            db_update_list.append(new_obj.product_name.product_name)
    except AttributeError:
        pass
    scheduler.add_job(update_product_db, 'date', run_date=timezone.now() + timezone.timedelta(seconds=1), id='update_product_db', replace_existing=True)


def agv_dummy():
    qs_transfer = AgvTransfer.objects.filter(id=1)
    obj_transfer = get_object_or_404(qs_transfer)
    obj_transfer.x_nav -= 1
    if obj_transfer.x_nav <= -61:
        obj_transfer.x_nav = 31
    obj_transfer.changeReason = 'Simulate AGV Moving'
    obj_transfer.save(update_fields=['x_nav'])


scheduler = BackgroundScheduler()
scheduler.add_job(initial, 'date', run_date=timezone.now() + timezone.timedelta(seconds=1), id='initial', replace_existing=True)
scheduler.add_job(robot_check, 'interval', seconds=2, id='robot_check', replace_existing=True)
scheduler.add_job(transfer_check, 'interval', seconds=2, id='transfer_check', replace_existing=True)
# scheduler.add_job(agv_dummy, 'interval', seconds=1, id='agv_dummy', replace_existing=True)

print(datetime_now() + 'Program Started')
logfile_update(logfilename, datetime_now() + 'Program Started')
try:
    db_update_list = list(Product.objects.all().values_list('product_name', flat=True))
except ProgrammingError:
    pass
update_product_db()
