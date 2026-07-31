// Releases Page Specific JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // Stream selector for release streams
    const streamSelect = document.getElementById('release-stream-select');
    const releaseStreams = document.querySelectorAll('.release-stream');

    // On internal dev: reveal the 26.1.x option in the selector
    const isDev = window.SITE_ENV && window.SITE_ENV.isDev;
    if (isDev && streamSelect) {
        const opt261 = streamSelect.querySelector('option[value="26.1.x"]');
        if (opt261) opt261.style.display = '';
        // Default to 26.1.x on internal dev
        streamSelect.value = '26.1.x';
        const stream261 = document.querySelector('[data-stream="26.1.x"]');
        const stream260 = document.querySelector('[data-stream="26.0.x"]');
        if (stream261) { stream261.style.display = 'block'; stream261.classList.add('active'); }
        if (stream260) { stream260.style.display = 'none'; stream260.classList.remove('active'); }
    }

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
    
    // Operator tab switching for component versions (26.0.0 GA)
    // Scoped to avoid matching operator-tab-261 tabs
    const operatorTabs = document.querySelectorAll('[data-operator]');
    const contentComponents = document.getElementById('content-components');
    const aiServicesComponents = document.getElementById('ai-services-components');

    operatorTabs.forEach(tab => {
        tab.addEventListener('click', function(e) {
            e.preventDefault();
            operatorTabs.forEach(t => t.classList.remove('active'));
            this.classList.add('active');

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

    // Operator tab switching for component versions (26.1.0 GA)
    const operatorTabs261 = document.querySelectorAll('[data-operator-261]');
    const contentComponents261 = document.getElementById('content-components-261');
    const aiServicesComponents261 = document.getElementById('ai-services-components-261');
    const wduServicesComponents261 = document.getElementById('wdu-services-components-261');
    const infraComponents261 = document.getElementById('infrastructure-components-261');

    operatorTabs261.forEach(tab => {
        tab.addEventListener('click', function(e) {
            e.preventDefault();
            operatorTabs261.forEach(t => t.classList.remove('active'));
            this.classList.add('active');

            const operator = this.getAttribute('data-operator-261');
            contentComponents261.style.display = operator === 'content' ? 'grid' : 'none';
            aiServicesComponents261.style.display = operator === 'ai-services' ? 'grid' : 'none';
            if (wduServicesComponents261) {
                wduServicesComponents261.style.display = operator === 'wdu-services' ? 'grid' : 'none';
            }
            infraComponents261.style.display = operator === 'infrastructure' ? 'grid' : 'none';
        });
    });
    
    // Operator tab switching for component versions (26.0.0 IF1)
    const operatorTabsIf1 = document.querySelectorAll('[data-operator-if1]');
    const contentComponentsIf1 = document.getElementById('content-components-if1');
    const aiServicesComponentsIf1 = document.getElementById('ai-services-components-if1');

    operatorTabsIf1.forEach(tab => {
        tab.addEventListener('click', function(e) {
            e.preventDefault();
            operatorTabsIf1.forEach(t => t.classList.remove('active'));
            this.classList.add('active');

            const operator = this.getAttribute('data-operator-if1');
            contentComponentsIf1.style.display = operator === 'content' ? 'grid' : 'none';
            aiServicesComponentsIf1.style.display = operator === 'ai-services' ? 'grid' : 'none';
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
