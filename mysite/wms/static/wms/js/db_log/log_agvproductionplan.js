$(document).ready(function () {
    var table = $('#dataTable').DataTable({
        dom: "<'row'<'col-sm-12 col-md-6'B><'col-sm-12 col-md-6'f>>" + "<'row'<'col-sm-12'tr>>" + "<'row'<'col-sm-12'l>>" + "<'row'<'col-sm-12 col-md-5'i><'col-sm-12 col-md-7'p>>",
        buttons: ['colvis', 'excel', 'print'],
        order: [[0, 'desc']],
        lengthMenu: [[10, 25, 50, 100, -1], [10, 25, 50, 100, 'All']],
        columns: [
            { data: 'history_date', className: "text-left" },
            { data: 'history_change_reason', className: "text-left" },
            { data: 'history_type', className: "text-left" },
            { data: 'history_user', className: "text-left" },
            { data: 'id', className: "text-left" },
            { data: 'product_name', className: "text-left" },
            { data: 'qty_total', className: "text-right" },
            { data: 'qty_remain', className: "text-right" },
            { data: 'lot_name', className: "text-left" },
        ],
        searching: true,
        processing: true,
        serverSide: true,
        stateSave: false,
        ajax: json_data,
        deferRender: true,
    });
});