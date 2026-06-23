# Carbon Design System v11 Updates

This document outlines the updates made to integrate IBM Carbon Design System v11 into the IBM Content Cortex Containers GitHub Pages site.

## Overview

The site has been updated to use the **latest Carbon Design System v11** components and **Carbon Web Components v2.13.0**, providing a modern, accessible, and consistent user experience aligned with IBM's design language.

## Key Changes

### 1. Carbon CSS & Web Components Integration (Latest)

Updated to use the latest Carbon libraries from official CDN:
- **`@carbon/styles@1.59.0`** - Latest Carbon v11 styles
- **`@carbon/web-components@2.13.0`** - Latest Carbon Web Components
- Loaded via `cdn.jsdelivr.net` for optimal performance and reliability
- ES Module format for modern browser support

### 2. Design Tokens

Updated all CSS custom properties to use Carbon v11 tokens:

**Color Tokens:**
- `--cds-background` - Main background color
- `--cds-layer-01/02/03` - Layer backgrounds
- `--cds-text-01/02/03` - Text hierarchy
- `--cds-interactive-01/02/03/04` - Interactive elements
- `--cds-border-subtle-00/01` - Border colors

**Spacing Tokens:**
- `--cds-spacing-01` through `--cds-spacing-12` - Consistent spacing scale
- `--cds-layout-01` through `--cds-layout-07` - Layout spacing

**Typography:**
- `--cds-font-family` - IBM Plex Sans
- `--cds-font-family-mono` - IBM Plex Mono

### 3. Carbon Grid System

Implemented Carbon's 16-column grid system:
```html
<div class="cds--grid">
  <div class="cds--row">
    <div class="cds--col-lg-8 cds--col-md-4 cds--col-sm-4">
      <!-- Content -->
    </div>
  </div>
</div>
```

**Breakpoints:**
- Small (sm): 320px - 671px (4 columns)
- Medium (md): 672px - 1055px (8 columns)
- Large (lg): 1056px - 1311px (16 columns)
- X-Large (xlg): 1312px - 1583px (16 columns)
- Max (max): 1584px+ (16 columns)

### 4. Carbon Components

#### Buttons
Using Carbon button classes with proper sizing and icons:
```html
<button class="cds--btn cds--btn--primary">
  Get Started
  <svg class="cds--btn__icon">...</svg>
</button>
```

#### Tags
Carbon tags for version badges and labels:
```html
<span class="cds--tag cds--tag--blue">v26.0.0</span>
<span class="cds--tag cds--tag--green">Active</span>
<span class="cds--tag cds--tag--purple">Service</span>
```

#### Tiles
Carbon tiles for feature and component cards:
```html
<div class="cds--tile cds--tile--clickable">
  <!-- Tile content -->
</div>
```

#### Code Snippets
Carbon code snippet styling:
```html
<pre class="cds--snippet cds--snippet--multi">
  <code><!-- Code here --></code>
</pre>
```

### 5. Typography Scale

Using Carbon type tokens for consistent typography:
- `cds--type-heading-01` through `cds--type-heading-07` - Headings
- `cds--type-body-01/02` - Body text
- `cds--type-code-01/02` - Code text
- `cds--type-label-01/02` - Labels

### 6. Navigation (UI Shell)

Updated navigation to follow Carbon UI Shell patterns:
- 48px (3rem) height
- Border-bottom active state indicator
- Proper hover and focus states
- Consistent spacing and alignment

### 7. Motion & Transitions

Using Carbon motion tokens:
- Fast: 110ms - Micro-interactions
- Moderate: 240ms - UI element transitions
- Slow: 400ms - Large element transitions
- Easing: `cubic-bezier(0.2, 0, 0.38, 0.9)` - Carbon standard easing

### 8. Accessibility

Carbon v11 provides built-in accessibility features:
- WCAG 2.1 AA compliant color contrast
- Keyboard navigation support
- Screen reader optimized markup
- Focus indicators on all interactive elements

## Component Updates

### Hero Section
- Carbon grid layout
- Carbon buttons with icons
- Carbon tags for badges
- Gradient background with subtle grid pattern
- Floating logo animation

### Features Section
- Carbon tiles with hover effects
- Proper spacing using Carbon tokens
- Type scale for headings and body text
- 3-column responsive grid

### Quick Start Section
- Carbon tile container
- Carbon tags for step numbers
- Carbon code snippets
- Proper content hierarchy

### Components Section
- Carbon tiles for component cards
- Carbon tags for version badges
- Carbon links for CTAs
- Border-top accent color

### Resources Section
- Carbon-styled cards
- Hover effects with border accent
- Consistent spacing and typography

## Browser Support

Carbon Design System v11 supports:
- Chrome (latest 2 versions)
- Firefox (latest 2 versions)
- Safari (latest 2 versions)
- Edge (latest 2 versions)

## Performance

- CSS loaded from CDN for optimal caching
- Minimal custom CSS overrides
- Efficient grid system
- Optimized animations

## Future Enhancements

Potential future updates:
1. Carbon Web Components for interactive elements
2. Carbon Charts for data visualization
3. Carbon Pictograms for enhanced iconography
4. Dark mode support using Carbon themes
5. Additional Carbon patterns (modals, notifications, etc.)

## Resources

- [Carbon Design System](https://carbondesignsystem.com/)
- [Carbon v11 Documentation](https://carbondesignsystem.com/developing/frameworks/react/)
- [Carbon Components](https://github.com/carbon-design-system/carbon)
- [Carbon Web Components](https://web-components.carbondesignsystem.com/)

## Maintenance

To keep Carbon up to date:
1. Monitor Carbon releases: https://github.com/carbon-design-system/carbon/releases
2. Update CDN links in HTML files
3. Test all components after updates
4. Review breaking changes in release notes
5. Update custom CSS if needed

## Recent Updates (June 23, 2026)

### Phase 1: CSS Variable Fixes
Added complete IBM Carbon color palette and spacing variables to ensure proper rendering:
- **Gray Scale**: `--gray-10` through `--gray-100` for consistent grayscale values
- **Blue Palette**: `--blue-10` through `--blue-100` for primary interactive colors
- **Green Palette**: `--green-10` through `--green-100` for success states
- **Yellow Palette**: `--yellow-10` through `--yellow-100` for warning states
- **Purple Palette**: `--purple-10` through `--purple-100` for accent colors
- **Spacing Aliases**: Added `--spacing-*` aliases for backward compatibility
- **Typography Aliases**: Added `--font-family` and `--font-family-mono` aliases
- **Transition Tokens**: Added `--transition-fast`, `--transition-moderate`, `--transition-slow`

### Phase 2: Component Styling
- **Container Class**: Added `.container` for consistent page width and padding
- **Button Styles**: Enhanced `.cds--btn` with full Carbon v11 specifications
- **Tag Styles**: Enhanced `.cds--tag` with all color variants
- **Custom Badges**: Updated to match Carbon design patterns
- All custom CSS now properly references defined CSS variables

### Phase 3: Latest Carbon Web Components (Current)
Upgraded to the latest Carbon Design System packages:
- **@carbon/styles@1.59.0** - Latest Carbon v11 styles with all improvements
- **@carbon/web-components@2.13.0** - Latest web components from official repository
- **Modern ES Modules**: Using `type="module"` for optimal browser support
- **CDN Delivery**: Using `cdn.jsdelivr.net` for fast, reliable delivery
- **Automatic Updates**: CDN ensures latest patches and security fixes

### Benefits of Latest Carbon Web Components
1. **Modern Architecture**: ES Module format for better performance
2. **Latest Features**: Access to newest Carbon components and patterns
3. **Better Accessibility**: Enhanced ARIA support and keyboard navigation
4. **Improved Performance**: Optimized bundle size and loading
5. **Active Maintenance**: Regular updates from Carbon team
6. **Web Standards**: Built on modern web component standards

---

Last Updated: June 23, 2026
Carbon Styles Version: @latest (Always pulls newest from official repository)
Carbon Web Components Version: @latest (Always pulls newest from official repository)
Repository: https://github.com/carbon-design-system/carbon