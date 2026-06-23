// Helm Charts Page Specific JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // Version tab switching functionality
    const versionTabs = document.querySelectorAll('.version-tab');
    const chartDetails = document.querySelectorAll('.chart-detail');
    
    versionTabs.forEach(tab => {
        tab.addEventListener('click', function() {
            const selectedVersion = this.getAttribute('data-version');
            
            // Remove active class from all version tabs
            versionTabs.forEach(t => t.classList.remove('active'));
            // Add active class to clicked tab
            this.classList.add('active');
            
            // Show/hide charts based on version
            chartDetails.forEach(chart => {
                const chartVersion = chart.getAttribute('data-version');
                if (chartVersion === selectedVersion) {
                    chart.style.display = 'block';
                } else {
                    chart.style.display = 'none';
                }
            });
        });
    });
    
    // Tab functionality for chart features/installation/values
    const tabButtons = document.querySelectorAll('.tab-button');
    
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const tabId = this.getAttribute('data-tab');
            const chartDetail = this.closest('.chart-detail');
            
            // Remove active class from all tabs in this chart
            chartDetail.querySelectorAll('.tab-button').forEach(btn => {
                btn.classList.remove('active');
            });
            
            // Remove active class from all tab contents in this chart
            chartDetail.querySelectorAll('.tab-content').forEach(content => {
                content.classList.remove('active');
            });
            
            // Add active class to clicked tab
            this.classList.add('active');
            
            // Show corresponding content
            const targetContent = chartDetail.querySelector(`#${tabId}`);
            if (targetContent) {
                targetContent.classList.add('active');
            }
        });
    });
    
    // Smooth scroll to chart sections
    const hash = window.location.hash;
    if (hash) {
        setTimeout(() => {
            const element = document.querySelector(hash);
            if (element) {
                element.scrollIntoView({ behavior: 'smooth', block: 'start' });
                // Highlight the chart briefly
                element.style.boxShadow = '0 0 0 4px rgba(15, 98, 254, 0.3)';
                setTimeout(() => {
                    element.style.boxShadow = '';
                }, 2000);
            }
        }, 100);
    }
    // Method tab switching for Complete Installation Guide
    const methodTabs = document.querySelectorAll('.method-tab');
    const methodContents = document.querySelectorAll('.method-content');
    
    methodTabs.forEach(tab => {
        tab.addEventListener('click', function() {
            const methodId = this.getAttribute('data-method');
            
            // Remove active class from all tabs
            methodTabs.forEach(t => t.classList.remove('active'));
            // Add active class to clicked tab
            this.classList.add('active');
            
            // Hide all method contents
            methodContents.forEach(content => {
                content.style.display = 'none';
                content.classList.remove('active');
            });
            
            // Show selected method content
            const targetContent = document.getElementById(`method-${methodId}`);
            if (targetContent) {
                targetContent.style.display = 'block';
                targetContent.classList.add('active');
            }
        });
    });
});

// Made with Bob
