// Helm Charts Page Specific JavaScript

document.addEventListener('DOMContentLoaded', function() {
    const chartDetails = document.querySelectorAll('.chart-detail');
    const streamSelect = document.getElementById('stream-select');
    const versionSelector261 = document.getElementById('version-selector-261');
    const versionSelector260 = document.getElementById('version-selector-260');

    // Show helm-charts for the given version string (e.g. "26.1.0")
    function showChartsForVersion(version) {
        chartDetails.forEach(chart => {
            const chartVersion = chart.getAttribute('data-version');
            const alsoVersions = [
                chart.getAttribute('data-also-version'),
                chart.getAttribute('data-also-version-2')
            ];
            const matches = chartVersion === version || alsoVersions.includes(version);
            chart.style.display = matches ? 'block' : 'none';
        });
    }

    // Switch between release streams
    function switchStream(stream) {
        if (stream === '26.1.x') {
            if (versionSelector261) versionSelector261.style.display = 'block';
            if (versionSelector260) versionSelector260.style.display = 'none';
            // Activate the first (only) tab in 26.1.x selector
            const tab261 = versionSelector261 && versionSelector261.querySelector('.version-tab');
            if (tab261) {
                versionSelector261.querySelectorAll('.version-tab').forEach(t => t.classList.remove('active'));
                tab261.classList.add('active');
                showChartsForVersion(tab261.getAttribute('data-version'));
            }
        } else {
            if (versionSelector261) versionSelector261.style.display = 'none';
            if (versionSelector260) versionSelector260.style.display = 'block';
            // Activate the "latest" tab in 26.0.x selector
            const activeTab260 = versionSelector260 && (
                versionSelector260.querySelector('.version-tab.active') ||
                versionSelector260.querySelector('.version-tab:last-child')
            );
            if (activeTab260) {
                versionSelector260.querySelectorAll('.version-tab').forEach(t => t.classList.remove('active'));
                activeTab260.classList.add('active');
                showChartsForVersion(activeTab260.getAttribute('data-version'));
            }
        }
    }

    // Stream selector change
    if (streamSelect) {
        streamSelect.addEventListener('change', function() {
            switchStream(this.value);
        });
    }

    // Version tab clicks (works across both selectors)
    const versionTabs = document.querySelectorAll('.version-tab');
    versionTabs.forEach(tab => {
        tab.addEventListener('click', function() {
            const parentSelector = this.closest('.version-selector');
            // Only deactivate tabs within the same selector block
            parentSelector.querySelectorAll('.version-tab').forEach(t => t.classList.remove('active'));
            this.classList.add('active');
            showChartsForVersion(this.getAttribute('data-version'));
        });
    });

    // Init: on public site default to 26.0.x; on internal dev allow 26.1.x
    const isDev = window.SITE_ENV && window.SITE_ENV.isDev;

    if (isDev) {
        // Reveal the 26.1.x <option> so internal devs can select it
        const opt261 = streamSelect && streamSelect.querySelector('option[value="26.1.x"]');
        if (opt261) opt261.style.display = '';
    }

    // Default stream: 26.0.x on public, 26.1.x on internal dev
    switchStream(isDev ? '26.1.x' : '26.0.x');
    if (streamSelect) streamSelect.value = isDev ? '26.1.x' : '26.0.x';
    
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
