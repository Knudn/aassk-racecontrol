
// Custom scripts can go here

// Enable Bootstrap tab toggle
$(document).ready(function () {
    $('#adminTabs a').on('click', function (e) {
        e.preventDefault()
        $(this).tab('show')
    })
});
