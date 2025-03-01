
document.addEventListener('DOMContentLoaded', (event) => {
    
    function handleSaveChangesClick(event) {
        event.preventDefault();
    
        var form = document.getElementById('assetForm');
        var formData = new FormData(form);
        
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/admin/infoscreen', true); // Update the URL to your form's action
        xhr.onload = function() {
            if (xhr.status === 200) {
                alert('Asset uploaded successfully.');
            } else {
                alert('An error occurred during the upload.');
            }
        };
        xhr.onerror = function() {
            alert('Network error occurred during the upload.');
        };
    
        xhr.send(formData);
    }


    function handleApproveButtonClick(event, func) {
        var button = event.currentTarget;
        var button_name = button.classList.value
        console.log(button_name)
        if (button.classList.contains('add-asset-button')) {

            var buttonId = button.getAttribute('data-button-id');
            var select_field = "#select_asset_" + buttonId
            var timer_field = "timer_field_" + buttonId
            var selectedAsset = document.querySelector(select_field +' select').value;
            var timer = document.getElementById(timer_field).value;
            var accordionButton = this.closest('.accordion-item').querySelector('.accordion-button');
            var accordionIndex = accordionButton.getAttribute('data-accordion-index');
            var action = "add"
            var messageData = {
                operation: 2,
                selectedAsset: selectedAsset,
                timer: timer,
                infoscreen: accordionIndex,
                action: action
            };
        }

    
        if (button_name == 'remove-btn') {
            var action = "remove";
        } else if (button_name == 'approve-btn') {
            var action = "approve";
        } else if (button_name == 'deactivate-btn') {
            var action = "deactivate";
        } else if (button_name == 'view-vnc-btn') {
            var port = "6080";
            var messageCard = event.target.closest('.info-message-card');
            var ip = messageCard.querySelector('.info-message-header span:nth-child(2)').textContent.replace('IP: ', '');
            window.open(`http://${ip}:${port}/vnc.html?host=${ip}&port=${port}&autoconnect=true`, '_blank');
            return
        } else {
            console.log('Button clicked does not have a specific class, performing default action');
        }
        
        if (button_name == 'remove-btn' || button_name == 'approve-btn' || button_name == 'deactivate-btn') {

            var messageCard = event.target.closest('.info-message-card');
            var hostname = messageCard.querySelector('.info-message-header span').textContent.replace('Hostname: ', '');
            var ip = messageCard.querySelector('.info-message-header span:nth-child(2)').textContent.replace('IP: ', '');
            var id = messageCard.querySelector('.info-message-header span:nth-child(3)').textContent.replace('ID: ', '');

            var messageData = {
                operation: 1,
                hostname: hostname,
                ip: ip,
                id: id,
                action: action
            };
        }


        var jsonData = JSON.stringify(messageData);
        console.log(jsonData)
        
        fetch("/admin/infoscreen", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: jsonData
        }).then(response => response.json())

        .then(data => {
            console.log(data);
            location.reload()
        }).catch(error => {
            console.error('Error:', error);
        });
        
    }

    document.querySelectorAll('.approve-btn').forEach(function(button) {
        button.addEventListener('click', handleApproveButtonClick);
    });
    document.querySelectorAll('.remove-btn').forEach(function(button) {
        button.addEventListener('click', handleApproveButtonClick);
    });
    document.querySelectorAll('.deactivate-btn').forEach(function(button) {
        button.addEventListener('click', handleApproveButtonClick);
    });
    document.querySelectorAll('.view-vnc-btn').forEach(function(button) {
        button.addEventListener('click', handleApproveButtonClick);
    });
    document.querySelectorAll('submit').forEach(function(button) {
        button.addEventListener('click', handleApproveButtonClick);
    });
    document.querySelectorAll('.add-asset-button').forEach(function(button) {
        console.log("asdasd")
        button.addEventListener('click', handleApproveButtonClick);
    });

    var saveChangesButton = document.querySelector('.save-changes-btn');
    if (saveChangesButton) {
        saveChangesButton.addEventListener('click', handleSaveChangesClick);
    } else {
        console.error('Save changes button not found!');
    }
});



    function populateModalSelector(data, deviceId) {
        // Construct the selector query using the device ID
        const selectorId = '#select_asset_' + deviceId + ' .form-select';
        const selector = document.querySelector(selectorId);
    
        // Clear existing options
        selector.innerHTML = '';
    
        // Populate with new data
        data.forEach(item => {
            const option = `<option value="${item.id}">${item.name}</option>`;
            selector.innerHTML += option;
        });
    }
    
    function deleteAsset(assetId) {
        console.log('Deleting asset with ID:', assetId);
        var jsonData = JSON.stringify({ id: assetId, action: 'delete', operation:1});
        console.log(jsonData)
        fetch('/admin/infoscreen', { 
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: jsonData
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok ' + response.statusText);
            }
            return response.json();
        })
        .then(data => {
            console.log(data);
            if (data.status === 'success') {
                // Find the table row and remove it without reloading the page
                document.querySelector(`#assetRow${assetId}`).remove();
            } 
            location.reload()
        })
        .catch(error => {
            console.error('Error:', error);

        });
    }

    $(document).ready(function() {
        // Target each sortable list
        $("[id^='sortable-']").each(function() {
            var currentId = $(this).attr('id');
            
            $('#' + currentId).sortable({
                cursor: 'move',
                opacity: 0.6,
                stop: function() {
                    var updatedRows = [];
    
                    // Iterate over each row in the current sortable table
                    $('#' + currentId + ' tr').each(function() {
                        var rowData = {
                            id: $(this).data("id"),
                            index: $(this).find("td[index]").text(),
                            name: $(this).find("td input[type='text']").eq(0).val(),
                            asset: $(this).find("td input[type='text']").eq(1).val(),
                            timer: $(this).find("td .timer_data").val()
                        };
                        updatedRows.push(rowData);
                    });
    
                    // Now you can send 'updatedRows' to your backend
                }
            });
        });
    });
    
    
    function sendOrderToServer(updatedOrder) {
        $.ajax({
            url: 'YOUR_BACKEND_URL', // Replace with your server URL
            method: 'POST',
            data: {
                order: updatedOrder
            },
            success: function(response) {
                // Handle success - you can show a message to the user, etc.
            },
            error: function() {
                // Handle error - you can show an error message, etc.
            }
        });
    }

    $(document).ready(function() {
        $('.remove-asset-button').click(function() {
            // Get the row where the button was clicked
            var row = $(this).closest('tr');
            row.remove();
        });
    });

    $(document).ready(function() {
        // Event delegation for dynamically generated content
        $(document).on('click', '.btn.btn-primary.mt-3', function() {
            var messageID = this.id.split('-')[1];
            var $table = $('#sortable-' + messageID);
            var tableData = [];
    
            $table.find('tr').each(function() {
                var $row = $(this);
                var rowData = {
                    index: $row.index() + 1,
                    name: $row.find('td:nth-child(2) input').val(),
                    asset: $row.find('td:nth-child(3) input').val(),
                    timer: $row.find('td:nth-child(4) input').val()
                };
                tableData.push(rowData);
            });
    
            // AJAX call to send data
            $.ajax({
                url: '/admin/infoscreen', // Replace with your server endpoint
                type: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ messageID: messageID, data: tableData, operation: 3 }),
                success: function(response) {
                    // Handle the response from the server
                    console.log('Success:', response);
                    location.reload()
                },
                error: function(error) {
                    // Handle errors
                    console.error('Error:', error);
                }
            });
        });
    });
    