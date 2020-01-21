$(document).ready(function () {
    /************************************************************************************************************************************************/
    // Refresh AgvProductionPlan
    function update_agvproductionplan() {
        $.ajax({
            url: api_agvproductionplan,
            type: 'GET',
            success: function (response) {
                render_agvproductionplan(response)
            }
        })
    }
    update_agvproductionplan()
    setInterval(update_agvproductionplan, 1000)

    // Refresh RobotQueue
    function update_robotqueue() {
        $.ajax({
            url: api_robotqueue,
            type: 'GET',
            success: function (response) {
                render_robotqueue(response)
            }
        })
    }
    update_robotqueue()
    setInterval(update_robotqueue, 1000)

    // Refresh AgvQueue
    function update_agvqueue() {
        $.ajax({
            url: api_agvqueue,
            type: 'GET',
            success: function (response) {
                render_agvqueue(response)
            }
        })
    }
    update_agvqueue()
    setInterval(update_agvqueue, 1000)

    // Refresh AgvTransfer
    function update_agvtransfer() {
        $.ajax({
            url: api_agvtransfer,
            type: 'GET',
            success: function (response) {
                render_agvtransfer(response)
            }
        })
    }
    update_agvtransfer()
    setInterval(update_agvtransfer, 1000)
    /************************************************************************************************************************************************/
    /* Auto Calculate Form */
    // Manual Transfeer
    path = 'form[name="manualtransfer-form"] '
    $(path + '#id_agv_no').change(function () {
        agv_no = $(path + '#id_agv_no').val()
        $('#agv_to_home').attr('href', url_agv_to_home[agv_no])
    })
    $(path + '#id_agv_no').change()
    /************************************************************************************************************************************************/
    // Enable Select2
    $('.select2').select2({
        theme: "bootstrap4",
        language: lang,
    })
    /************************************************************************************************************************************************/
})