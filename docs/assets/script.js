// ─────────────────────────────────────────────────────────────────────────────
// Environment Detection & URL Configuration
// Detects whether the page is served from the private IBM GitHub Enterprise
// Pages host (dev) or the public GitHub.com Pages host (prod) and exposes a
// global SITE_ENV object consumed by all pages.
// ─────────────────────────────────────────────────────────────────────────────

(function () {
    var hostname = window.location.hostname;
    var isDev = hostname === 'pages.github.ibm.com' || hostname.endsWith('.github.ibm.com');

    window.SITE_ENV = {
        isDev: isDev,

        // Helm chart repository base URL (used for download hrefs)
        pagesBase: isDev
            ? 'https://pages.github.ibm.com/ecm-container-service/container-samples'
            : 'https://ibm-ecm.github.io/ibm-content-cortex-containers',

        // Raw content base URL — bypasses SSO, accepts GHE token auth (internal only)
        // Used for helm repo add on the internal site
        rawBase: isDev
            ? 'https://raw.github.ibm.com/ecm-container-service/container-samples/gh-pages/docs'
            : null,

        // Git repository base URL (used for clone commands, issue links, nav links)
        repoBase: isDev
            ? 'https://github.ibm.com/ecm-container-service/container-samples'
            : 'https://github.com/ibm-ecm/ibm-content-cortex-containers',

        // Token settings page URL (internal only)
        tokenUrl: isDev
            ? 'https://github.ibm.com/settings/tokens/new?description=ibm-content-cortex-helm&scopes=repo'
            : null,

        repoName: isDev ? 'container-samples' : 'ibm-content-cortex-containers',

        label: isDev ? 'Internal Dev' : 'Public'
    };
})();

// ─────────────────────────────────────────────────────────────────────────────
// DOM URL Rewriting
// Elements decorated with data-href-env or data-text-env are rewritten on load.
//
// data-href-env="pagesBase/helm-charts/ibm-content-operator-26.0.1.tgz"
//   → sets element href to SITE_ENV.pagesBase + '/helm-charts/...'
//
// data-text-env="repoBase"
//   → sets element textContent to SITE_ENV[key]
//
// data-code-env="repoBase"
//   → sets element textContent AND parent <pre> copy-button text to SITE_ENV[key]
// ─────────────────────────────────────────────────────────────────────────────

function applyEnvUrls() {
    var env = window.SITE_ENV;

    // ── href rewrites ──────────────────────────────────────────────────────
    document.querySelectorAll('[data-href-env]').forEach(function (el) {
        var template = el.getAttribute('data-href-env');
        var resolved = resolveTemplate(template, env);
        el.setAttribute('href', resolved);
    });

    // ── inline text rewrites (single-line display elements, NOT <pre>) ─────
    // Used on <code class="info-value">, <li><code>, etc.
    document.querySelectorAll('[data-text-env]').forEach(function (el) {
        var template = el.getAttribute('data-text-env');
        el.textContent = resolveTemplate(template, env);
    });

    // ── <pre> code block rewrites (data-cmd attribute on the <pre>) ────────
    // Template tokens: {pagesBase} {rawBase} {repoBase} {repoName}
    // Writes clean textContent to the <code> child so the copy button works.
    document.querySelectorAll('pre[data-cmd]').forEach(function (pre) {
        var template = pre.getAttribute('data-cmd');
        var resolved = template
            .replace(/\{pagesBase\}/g, env.pagesBase)
            .replace(/\{rawBase\}/g, env.rawBase || env.pagesBase)
            .replace(/\{repoBase\}/g, env.repoBase)
            .replace(/\{repoName\}/g, env.repoName);
        var codeEl = pre.querySelector('code');
        if (codeEl) {
            codeEl.textContent = resolved;
        }
    });

    // ── show/hide environment-conditional elements ─────────────────────────
    document.querySelectorAll('[data-internal-only]').forEach(function (el) {
        el.style.display = env.isDev ? '' : 'none';
    });
    document.querySelectorAll('[data-public-only]').forEach(function (el) {
        el.style.display = env.isDev ? 'none' : '';
    });

    // ── dev environment badge ──────────────────────────────────────────────
    if (env.isDev) {
        var brand = document.querySelector('.nav-brand');
        if (brand) {
            var badge = document.createElement('span');
            badge.className = 'env-badge';
            badge.textContent = '🔒 Internal Dev';
            brand.appendChild(badge);
        }
    }
}

function resolveTemplate(template, env) {
    // Replace known key prefixes (used for href and text rewrites)
    return template
        .replace(/^pagesBase/, env.pagesBase)
        .replace(/^rawBase/, env.rawBase)
        .replace(/^repoBase/, env.repoBase);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyEnvUrls);
} else {
    applyEnvUrls();
}

// ─────────────────────────────────────────────────────────────────────────────
// Navigation Toggle for Mobile
// ─────────────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
    var navToggle = document.getElementById('navToggle');
    var navMenu = document.getElementById('navMenu');
    
    if (navToggle && navMenu) {
        navToggle.addEventListener('click', function() {
            navMenu.classList.toggle('active');
            
            // Animate hamburger icon
            var spans = navToggle.querySelectorAll('span');
            if (navMenu.classList.contains('active')) {
                spans[0].style.transform = 'rotate(45deg) translate(5px, 5px)';
                spans[1].style.opacity = '0';
                spans[2].style.transform = 'rotate(-45deg) translate(7px, -6px)';
            } else {
                spans[0].style.transform = 'none';
                spans[1].style.opacity = '1';
                spans[2].style.transform = 'none';
            }
        });
        
        // Close menu when clicking outside
        document.addEventListener('click', function(event) {
            if (!navToggle.contains(event.target) && !navMenu.contains(event.target)) {
                navMenu.classList.remove('active');
                var spans = navToggle.querySelectorAll('span');
                spans[0].style.transform = 'none';
                spans[1].style.opacity = '1';
                spans[2].style.transform = 'none';
            }
        });
        
        // Close menu when clicking a link
        var navLinks = navMenu.querySelectorAll('.nav-link');
        navLinks.forEach(function(link) {
            link.addEventListener('click', function() {
                navMenu.classList.remove('active');
                var spans = navToggle.querySelectorAll('span');
                spans[0].style.transform = 'none';
                spans[1].style.opacity = '1';
                spans[2].style.transform = 'none';
            });
        });
    }
});

// ─────────────────────────────────────────────────────────────────────────────
// Smooth Scroll for Anchor Links
// ─────────────────────────────────────────────────────────────────────────────

document.querySelectorAll('a[href^="#"]').forEach(function(anchor) {
    anchor.addEventListener('click', function (e) {
        var href = this.getAttribute('href');
        if (href !== '#' && href !== '' && href.startsWith('#')) {
            e.preventDefault();
            var target = document.querySelector(href);
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        }
    });
});

// ─────────────────────────────────────────────────────────────────────────────
// Scroll Animation
// ─────────────────────────────────────────────────────────────────────────────

var observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
};

var observer = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
        if (entry.isIntersecting) {
            entry.target.style.opacity = '1';
            entry.target.style.transform = 'translateY(0)';
        }
    });
}, observerOptions);

document.addEventListener('DOMContentLoaded', function() {
    var animatedElements = document.querySelectorAll('.feature-card, .component-card, .resource-card, .step');
    animatedElements.forEach(function(el) {
        el.style.opacity = '0';
        el.style.transform = 'translateY(20px)';
        el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(el);
    });
});

// ─────────────────────────────────────────────────────────────────────────────
// Copy Code to Clipboard
// ─────────────────────────────────────────────────────────────────────────────

function addCopyButtons() {
    var codeBlocks = document.querySelectorAll('pre code');
    codeBlocks.forEach(function(block) {
        var pre = block.parentElement;
        var button = document.createElement('button');
        button.className = 'copy-button';
        button.textContent = 'Copy';
        button.addEventListener('click', function() {
            var code = block.textContent;
            navigator.clipboard.writeText(code).then(function() {
                button.textContent = 'Copied!';
                setTimeout(function() {
                    button.textContent = 'Copy';
                }, 2000);
            });
        });
        pre.style.position = 'relative';
        pre.appendChild(button);
    });
}

document.addEventListener('DOMContentLoaded', addCopyButtons);

// ─────────────────────────────────────────────────────────────────────────────
// Filter Functionality
// ─────────────────────────────────────────────────────────────────────────────

function initializeFilters() {
    var filterButtons = document.querySelectorAll('[data-filter]');
    var filterItems = document.querySelectorAll('[data-category]');
    
    if (filterButtons.length > 0 && filterItems.length > 0) {
        filterButtons.forEach(function(button) {
            button.addEventListener('click', function() {
                var filter = this.getAttribute('data-filter');
                
                filterButtons.forEach(function(btn) { btn.classList.remove('active'); });
                this.classList.add('active');
                
                filterItems.forEach(function(item) {
                    var category = item.getAttribute('data-category');
                    if (filter === 'all' || category === filter) {
                        item.style.display = '';
                        setTimeout(function() {
                            item.style.opacity = '1';
                            item.style.transform = 'scale(1)';
                        }, 10);
                    } else {
                        item.style.opacity = '0';
                        item.style.transform = 'scale(0.95)';
                        setTimeout(function() {
                            item.style.display = 'none';
                        }, 300);
                    }
                });
            });
        });
    }
}

document.addEventListener('DOMContentLoaded', initializeFilters);

// ─────────────────────────────────────────────────────────────────────────────
// Search Functionality
// ─────────────────────────────────────────────────────────────────────────────

function initializeSearch() {
    var searchInput = document.getElementById('searchInput');
    var searchItems = document.querySelectorAll('[data-searchable]');
    
    if (searchInput && searchItems.length > 0) {
        searchInput.addEventListener('input', function() {
            var query = this.value.toLowerCase();
            searchItems.forEach(function(item) {
                var text = item.getAttribute('data-searchable').toLowerCase();
                item.style.display = text.includes(query) ? '' : 'none';
            });
        });
    }
}

document.addEventListener('DOMContentLoaded', initializeSearch);

// ─────────────────────────────────────────────────────────────────────────────
// Version Comparison (releases page utility)
// ─────────────────────────────────────────────────────────────────────────────

function compareVersions(v1, v2) {
    var parts1 = v1.split('.').map(Number);
    var parts2 = v2.split('.').map(Number);
    
    for (var i = 0; i < Math.max(parts1.length, parts2.length); i++) {
        var part1 = parts1[i] || 0;
        var part2 = parts2[i] || 0;
        if (part1 > part2) return 1;
        if (part1 < part2) return -1;
    }
    return 0;
}

// ─────────────────────────────────────────────────────────────────────────────
// Accordion Expand/Collapse
// ─────────────────────────────────────────────────────────────────────────────

function initializeAccordions() {
    var accordionHeaders = document.querySelectorAll('.accordion-header');
    
    accordionHeaders.forEach(function(header) {
        header.addEventListener('click', function() {
            var content = this.nextElementSibling;
            var isOpen = content.style.maxHeight;
            
            document.querySelectorAll('.accordion-content').forEach(function(item) {
                item.style.maxHeight = null;
                item.previousElementSibling.classList.remove('active');
            });
            
            if (!isOpen) {
                content.style.maxHeight = content.scrollHeight + 'px';
                this.classList.add('active');
            }
        });
    });
}

document.addEventListener('DOMContentLoaded', initializeAccordions);

// Made with Bob
