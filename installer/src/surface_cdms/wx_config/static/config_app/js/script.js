// redirect to the SURFACE config page based on users choice
document.addEventListener('DOMContentLoaded', function() {
    const installSurfaceForm = document.getElementById('installTypeForm');
    const installSurfaceRadios = installSurfaceForm.querySelectorAll('input[type="radio"]');

    installSurfaceRadios.forEach(radio => {
        radio.addEventListener('click', function() {
            installSurfaceForm.submit();
        });
    });
});

// Get all elements with the 'unavailable' class
const unavailableOptions = document.querySelectorAll('.option.unavailable');

// Add event listeners for each element to change text on hover and revert on mouseout
unavailableOptions.forEach(option => {
    option.addEventListener('mouseover', function() {
        this.textContent = 'UNAVAILABLE';
    });

    option.addEventListener('mouseout', function() {
        this.textContent = this.dataset.originalText || 'UNAVAILABLE';
    });

    // Store original text in dataset to revert back on mouseout
    option.dataset.originalText = option.textContent;
});