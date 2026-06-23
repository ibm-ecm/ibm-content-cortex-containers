// Releases Page Specific JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // Stream selector for release streams
    const streamSelect = document.getElementById('release-stream-select');
    const releaseStreams = document.querySelectorAll('.release-stream');
    
    if (streamSelect) {
        streamSelect.addEventListener('change', function() {
            const selectedStream = this.value;
            
            // Hide all streams
            releaseStreams.forEach(stream => {
                stream.style.display = 'none';
                stream.classList.remove('active');
            });
            
            // Show selected stream
            const targetStream = document.querySelector(`[data-stream="${selectedStream}"]`);
            if (targetStream) {
                targetStream.style.display = 'block';
                targetStream.classList.add('active');
            }
        });
    }
    
    // Operator tab switching for component versions
    const operatorTabs = document.querySelectorAll('.operator-tab');
    const contentComponents = document.getElementById('content-components');
    const aiServicesComponents = document.getElementById('ai-services-components');
    
    operatorTabs.forEach(tab => {
        tab.addEventListener('click', function() {
            // Remove active class from all tabs
            operatorTabs.forEach(t => t.classList.remove('active'));
            // Add active class to clicked tab
            this.classList.add('active');
            
            // Show/hide component lists
            const operator = this.getAttribute('data-operator');
            if (operator === 'content') {
                contentComponents.style.display = 'grid';
                aiServicesComponents.style.display = 'none';
            } else if (operator === 'ai-services') {
                contentComponents.style.display = 'none';
                aiServicesComponents.style.display = 'grid';
            }
        });
    });
    
    // Expand/collapse release details (optional functionality)
    const releaseHeaders = document.querySelectorAll('.release-header');
    
    releaseHeaders.forEach(header => {
        header.style.cursor = 'pointer';
        
        header.addEventListener('click', function(e) {
            // Don't collapse if clicking on a button or link
            if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON' || e.target.closest('a') || e.target.closest('button')) {
                return;
            }
            
            const content = this.nextElementSibling;
            if (content && content.classList.contains('release-content')) {
                content.style.display = content.style.display === 'none' ? 'flex' : 'none';
            }
        });
    });
    
    // Smooth scroll to iFix section if hash is present
    if (window.location.hash === '#ifixes') {
        setTimeout(() => {
            const ifixSection = document.querySelector('.ifix-section');
            if (ifixSection) {
                ifixSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        }, 100);
    }
});

// Made with Bob
