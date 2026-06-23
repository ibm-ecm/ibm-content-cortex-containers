# Carbon Design System v11 - Implementation Guide

## Overview

This GitHub Pages site uses the **latest Carbon Design System v11** with **Carbon Web Components v2.13.0** from the official Carbon repository at https://github.com/carbon-design-system/carbon.

## Architecture

### Modern Carbon Stack

```
┌─────────────────────────────────────────┐
│   Carbon Web Components v2.13.0         │
│   (ES Modules - Modern Browser Support) │
├─────────────────────────────────────────┤
│   @carbon/styles v1.59.0                │
│   (Latest Carbon v11 Design Tokens)     │
├─────────────────────────────────────────┤
│   Custom Styles (styles.css)            │
│   (Site-specific overrides)             │
└─────────────────────────────────────────┘
```

## Implementation Details

### 1. HTML Structure

All HTML files include the latest Carbon libraries:

```html
<!-- Carbon Design System v11 - Latest from Official Repository -->
<!-- https://github.com/carbon-design-system/carbon/tree/main/packages/styles -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@carbon/styles@latest/css/styles.min.css">

<!-- Carbon Web Components - Latest from Official Repository -->
<!-- https://github.com/carbon-design-system/carbon/tree/main/packages/web-components -->
<script type="module" src="https://cdn.jsdelivr.net/npm/@carbon/web-components@latest/dist/index.min.js"></script>

<!-- Custom Styles -->
<link rel="stylesheet" href="./assets/styles.css">
```

**Note**: Using `@latest` ensures the site always pulls the newest stable version from the official Carbon Design System repository, automatically receiving updates, bug fixes, and new features.

### 2. CSS Variables

Complete IBM Carbon color palette and design tokens:

```css
:root {
    /* Gray Scale */
    --gray-10: #f4f4f4;
    --gray-20: #e0e0e0;
    /* ... through gray-100 */
    
    /* Blue Palette */
    --blue-60: #0f62fe;
    --blue-70: #0043ce;
    /* ... complete blue scale */
    
    /* Spacing Scale */
    --spacing-01: 0.125rem;
    --spacing-02: 0.25rem;
    /* ... through spacing-12 */
    
    /* Typography */
    --font-family: 'IBM Plex Sans', sans-serif;
    --font-family-mono: 'IBM Plex Mono', monospace;
    
    /* Transitions */
    --transition-fast: 110ms cubic-bezier(0.2, 0, 0.38, 0.9);
    --transition-moderate: 240ms cubic-bezier(0.2, 0, 0.38, 0.9);
}
```

### 3. Carbon Components Used

#### Buttons
```html
<!-- Carbon Button -->
<button class="cds--btn cds--btn--primary">
    Primary Button
</button>

<!-- Custom Button -->
<a href="#" class="btn btn-primary">
    Custom Button
</a>
```

#### Tags
```html
<!-- Carbon Tags -->
<span class="cds--tag cds--tag--blue">v26.0.0</span>
<span class="cds--tag cds--tag--green">Active</span>
<span class="cds--tag cds--tag--purple">Service</span>
```

#### Tiles
```html
<!-- Carbon Tile -->
<div class="cds--tile cds--tile--clickable">
    <h3>Feature Title</h3>
    <p>Feature description</p>
</div>
```

#### Grid System
```html
<!-- Carbon 16-column Grid -->
<div class="cds--grid">
    <div class="cds--row">
        <div class="cds--col-lg-8 cds--col-md-4 cds--col-sm-4">
            Content
        </div>
    </div>
</div>
```

## Component Styling

### Carbon Button Styles

```css
.cds--btn {
    display: inline-flex;
    align-items: center;
    min-height: 3rem;
    padding: calc(0.875rem - 3px) 60px calc(0.875rem - 3px) 16px;
    font-size: 0.875rem;
    transition: background 70ms cubic-bezier(0, 0, 0.38, 0.9);
}

.cds--btn--primary {
    background-color: var(--blue-60);
    color: var(--white);
}

.cds--btn--primary:hover {
    background-color: var(--blue-70);
}
```

### Carbon Tag Styles

```css
.cds--tag {
    display: inline-flex;
    align-items: center;
    padding: 0 var(--spacing-03);
    height: 1.5rem;
    border-radius: 0.9375rem;
    font-size: 0.75rem;
    letter-spacing: 0.32px;
}

.cds--tag--blue {
    background-color: var(--blue-20);
    color: var(--blue-70);
}
```

## Custom Components

### Custom Badges

All custom badges follow Carbon design patterns:

```css
.chart-version,
.scope-badge,
.release-type,
.ifix-badge {
    display: inline-flex;
    align-items: center;
    padding: var(--spacing-02) var(--spacing-04);
    border-radius: 0.9375rem;
    font-size: 0.75rem;
    font-weight: 600;
    line-height: 1.33333;
    letter-spacing: 0.32px;
}
```

## Responsive Design

### Breakpoints

Carbon uses these breakpoints:

- **Small (sm)**: 320px - 671px (4 columns)
- **Medium (md)**: 672px - 1055px (8 columns)
- **Large (lg)**: 1056px - 1311px (16 columns)
- **X-Large (xlg)**: 1312px - 1583px (16 columns)
- **Max**: 1584px+ (16 columns)

### Grid Usage

```html
<!-- Responsive columns -->
<div class="cds--col-lg-8 cds--col-md-4 cds--col-sm-4">
    <!-- Content adapts to screen size -->
</div>
```

## Accessibility

Carbon v11 provides built-in accessibility:

- ✅ WCAG 2.1 AA compliant color contrast
- ✅ Keyboard navigation support
- ✅ Screen reader optimized markup
- ✅ Focus indicators on all interactive elements
- ✅ ARIA labels and roles

## Performance

### CDN Benefits

Using `cdn.jsdelivr.net`:
- Fast global delivery
- Automatic caching
- High availability
- Automatic updates to patch versions

### Loading Strategy

```html
<!-- CSS loads first (blocking) -->
<link rel="stylesheet" href=".../@carbon/styles@1.59.0/css/styles.min.css">

<!-- JS loads as module (non-blocking) -->
<script type="module" src=".../@carbon/web-components@2.13.0/dist/index.min.js"></script>
```

## Browser Support

Carbon Web Components v2.13.0 supports:

- ✅ Chrome (latest 2 versions)
- ✅ Firefox (latest 2 versions)
- ✅ Safari (latest 2 versions)
- ✅ Edge (latest 2 versions)
- ✅ Modern mobile browsers

## Maintenance

### Updating Carbon

To update to newer versions:

1. Check latest versions:
   - https://www.npmjs.com/package/@carbon/styles
   - https://www.npmjs.com/package/@carbon/web-components

2. Update CDN links in HTML files:
   ```html
   <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@carbon/styles@[VERSION]/css/styles.min.css">
   <script type="module" src="https://cdn.jsdelivr.net/npm/@carbon/web-components@[VERSION]/dist/index.min.js"></script>
   ```

3. Test all pages for compatibility

4. Update version numbers in documentation

### Testing Checklist

- [ ] All buttons render correctly
- [ ] All tags display proper colors
- [ ] Grid system is responsive
- [ ] Navigation works on mobile
- [ ] All links are functional
- [ ] Code snippets have copy buttons
- [ ] Accessibility features work
- [ ] Page loads quickly

## Resources

- **Carbon Design System**: https://carbondesignsystem.com/
- **Carbon Web Components**: https://github.com/carbon-design-system/carbon/tree/main/packages/web-components
- **Carbon Styles**: https://github.com/carbon-design-system/carbon/tree/main/packages/styles
- **Carbon Documentation**: https://carbondesignsystem.com/developing/frameworks/web-components/
- **IBM Design Language**: https://www.ibm.com/design/language/

## Support

For issues or questions:
- Carbon GitHub: https://github.com/carbon-design-system/carbon/issues
- Carbon Slack: https://carbondesignsystem.com/help/support/

---

**Last Updated**: June 23, 2026
**Carbon Styles**: @latest (Auto-updates from official repository)
**Carbon Web Components**: @latest (Auto-updates from official repository)
**Official Repository**: https://github.com/carbon-design-system/carbon
**Status**: ✅ Production Ready with Auto-Updates