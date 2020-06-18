from rest_framework import serializers

from .sched import *


class AgvStatusSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        obj_transfer = get_object_or_404(AgvTransfer, id=data['id'])
        data['agv_col'] = int(obj_transfer.agv_col)
        data['agv_row'] = int(obj_transfer.agv_row)
        data['agv_direction'] = obj_transfer.agv_direction
        return data

    class Meta:
        model = AgvTransfer
        fields = ['id']


class RobotStatusSerializer(serializers.ModelSerializer):
    qty_act = serializers.IntegerField()

    class Meta:
        model = RobotStatus
        fields = ['robot_no', 'qty_act']


class AgvRobotStatusSerializer(serializers.Serializer):
    agv_status = AgvStatusSerializer()
    robot_status = RobotStatusSerializer()


class AgvTransferSerializer(serializers.ModelSerializer):
    run = serializers.CharField(source='get_run_display')
    pause = serializers.CharField(source='get_pause_display')
    status = serializers.CharField(source='get_status_display')
    step = serializers.IntegerField(source='get_step_display')
    x_nav = serializers.DecimalField(max_digits=10, decimal_places=4)
    y_nav = serializers.DecimalField(max_digits=10, decimal_places=4)
    beta_nav = serializers.DecimalField(max_digits=10, decimal_places=1)
    pattern = serializers.CharField(source='get_pattern_display')

    class Meta:
        model = AgvTransfer
        fields = ['id', 'run', 'pause', 'status', 'step', 'x_nav', 'y_nav', 'beta_nav', 'agv_col', 'agv_row', 'pattern', 'col1', 'row1', 'col2', 'row2', 'col3', 'row3', 'col4', 'row4']


class AgvProductionPlanSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        for field in ['lot_name']:
            if not data[field]:
                data[field] = ''
        return data

    class Meta:
        model = AgvProductionPlan
        fields = ['id', 'product_name', 'lot_name', 'qty_total', 'qty_remain', 'percent_complete']


class RobotQueueSerializer(serializers.ModelSerializer):
    robot_no = serializers.CharField(source='get_robot_no_display')
    product_id = serializers.SerializerMethodField('get_product_id')
    updated = serializers.CharField(source='get_updated_display')

    def get_product_id(self, obj):
        return obj.product_id.product_name.product_name

    class Meta:
        model = RobotQueue
        fields = ['id', 'robot_no', 'product_id', 'qty_act', 'updated']


class AgvQueueSerializer(serializers.ModelSerializer):
    robot_no = serializers.CharField(source='get_robot_no_display')
    mode = serializers.CharField(source='get_mode_display')

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for field in ['product_name', 'lot_name', 'robot_no', 'pick_id', 'place_id', 'agv_no']:
            if not data[field]:
                data[field] = ''
        return data

    class Meta:
        model = AgvQueue
        fields = ['id', 'product_name', 'lot_name', 'qty_act', 'robot_no', 'pick_id', 'place_id', 'mode', 'agv_no']


class ProductSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        for field in ['plant']:
            if not data[field]:
                data[field] = ''
        return data

    class Meta:
        model = Product
        fields = ['product_name', 'name_eng', 'plant', 'qty_limit', 'qty_storage', 'qty_inventory', 'qty_buffer', 'qty_misplace', 'qty_total', 'qty_storage_avail', 'qty_inventory_avail']


class StorageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Storage
        fields = ['storage_id', 'is_inventory', 'storage_for', 'have_inventory', 'inv_product', 'name_eng', 'inv_qty', 'lot_name', 'created_on', 'updated_on']


class ProductHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Product.history.model
        fields = ['history_date', 'history_type', 'history_change_reason', 'product_name', 'qty_storage', 'qty_inventory', 'qty_buffer', 'qty_misplace', 'qty_total', 'qty_storage_avail', 'qty_inventory_avail']


class StorageHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Storage.history.model
        fields = ['history_date', 'history_type', 'history_change_reason', 'storage_id', 'is_inventory', 'storage_for', 'have_inventory', 'inv_product', 'inv_qty']


class AgvProductionPlanHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AgvProductionPlan.history.model
        fields = ['history_date', 'history_type', 'history_change_reason', 'id', 'product_name', 'qty_total', 'qty_remain', 'lot_name']


class RobotQueueHistorySerializer(serializers.ModelSerializer):
    robot_no = serializers.CharField(source='get_robot_no_display')
    product_id = serializers.SerializerMethodField('get_product_id')

    def get_product_id(self, obj):
        return obj.product_id.product_name.product_name

    class Meta:
        model = RobotQueue.history.model
        fields = ['history_date', 'history_type', 'history_change_reason', 'id', 'robot_no', 'product_id', 'qty_act']


class AgvQueueHistorySerializer(serializers.ModelSerializer):
    robot_no = serializers.CharField(source='get_robot_no_display')
    mode = serializers.CharField(source='get_mode_display')

    class Meta:
        model = AgvQueue.history.model
        fields = ['history_date', 'history_type', 'history_change_reason', 'id', 'product_name', 'lot_name', 'qty_act', 'created_on', 'robot_no', 'pick_id', 'place_id', 'mode']


class AgvTransferHistorySerializer(serializers.ModelSerializer):
    run = serializers.CharField(source='get_run_display')
    status = serializers.CharField(source='get_status_display')
    step = serializers.IntegerField(source='get_step_display')
    pause = serializers.CharField(source='get_pause_display')
    pattern = serializers.CharField(source='get_pattern_display')

    class Meta:
        model = AgvTransfer.history.model
        fields = ['history_date', 'history_type', 'history_change_reason', 'id', 'run', 'status', 'step', 'pause', 'pattern']


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
