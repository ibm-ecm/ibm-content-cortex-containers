# IBM Content Cortex GitHub Pages

This directory contains the GitHub Pages site for the IBM Content Cortex Containers repository.

## 🌐 Live Site

The site is published at: `https://ibm-ecm.github.io/ibm-content-cortex-containers`

## 📁 Structure

```
docs/
├── index.html              # Home page
├── helm-charts.html        # Helm charts repository page
├── releases.html           # Releases and patches page
├── README.md              # This file
├── IMPLEMENTATION_GUIDE.md # Carbon Design System guide
├── charts/                 # Helm chart repository
│   ├── index.yaml         # Helm repository index
│   ├── *.tgz              # Helm chart packages
│   └── README.md          # Chart repository documentation
└── assets/
    ├── ContentCortex.svg  # Logo
    ├── favicon.svg        # Favicon
    ├── styles.css         # Main stylesheet (IBM Carbon design)
    ├── script.js          # Main JavaScript
    ├── helm-charts.css    # Helm charts page styles
    ├── helm-charts.js     # Helm charts page scripts
    ├── releases.css       # Releases page styles
    └── releases.js        # Releases page scripts
```

## 🎨 Design System

The site uses **IBM Carbon Design System** principles:

- **Typography**: IBM Plex Sans and IBM Plex Mono
- **Colors**: IBM Carbon color palette (Blue 60, Gray scale)
- **Spacing**: IBM Carbon spacing scale
- **Components**: Cards, buttons, navigation, tabs, badges

## 📄 Pages

### Home Page (`index.html`)
- Hero section with product overview
- Key features grid
- Quick start guide
- Component showcase
- Resource links

### Helm Charts Page (`helm-charts.html`)
- Repository information and quick add commands
- Detailed chart information with tabs:
  - Features
  - Installation instructions
  - Configuration values
- Complete installation guide
- Available charts:
  - IBM Content Operator
  - IBM AI Services Operator
  - IBM License Service
  - IBM Usage Metering

### Releases & Patches Page (`releases.html`)
- Release stream selector (26.0.x, 25.0.x, 24.0.x)
- Detailed release information:
  - What's new
  - Component versions
  - System requirements
  - Resources
- iFix/patch tracking section (template ready)
- Upgrade guide with supported paths

## 🚀 Features

### Navigation
- Responsive navigation bar
- Mobile hamburger menu
- Active page highlighting
- Smooth scrolling

### Interactive Elements
- Tab switching for chart details
- Release stream filtering
- Collapsible sections
- Copy-to-clipboard for code blocks
- Smooth animations on scroll

### Responsive Design
- Mobile-first approach
- Breakpoints: 480px, 768px, 1056px
- Flexible grid layouts
- Touch-friendly interactions

## 🔧 Maintenance

### Adding New Releases

1. Edit `releases.html`
2. Add new release card in appropriate stream section
3. Update component versions
4. Add release notes and links

### Adding iFixes

1. Locate the iFix section for the release stream
2. Copy the iFix card template (currently hidden)
3. Update with ifix details:
   - Version number
   - Release date
   - Issues resolved
   - Updated components
   - Download links

### Updating Helm Charts

1. Add new chart `.tgz` file to `charts/` directory
2. Update `charts/index.yaml` using `helm repo index`
3. Edit `helm-charts.html` to update chart versions and metadata
4. Update download links to point to `/charts/` subdirectory

**Regenerating the Helm repository index:**
```bash
helm repo index docs/charts --url https://ibm-ecm.github.io/ibm-content-cortex-containers/charts
```

## 📝 Content Guidelines

### Writing Style
- Clear, concise, technical
- Use active voice
- Include code examples
- Link to official documentation

### Code Blocks
- Use syntax highlighting
- Include comments for clarity
- Show complete, working examples
- Add copy buttons automatically

### Links
- Use descriptive link text
- Open external links in new tabs
- Link to official IBM documentation
- Include GitHub release links

## 🎯 SEO & Accessibility

- Semantic HTML5 elements
- Proper heading hierarchy
- Alt text for images
- ARIA labels for interactive elements
- Meta descriptions
- Responsive images

## 🔄 Deployment

The site is automatically deployed via GitHub Pages when changes are pushed to the `main` branch in the `docs/` directory.

### GitHub Pages Settings
- Source: `main` branch, `/docs` folder
- Custom domain: (optional)
- HTTPS: Enabled

## 📦 Dependencies

### Fonts
- IBM Plex Sans (Google Fonts)
- IBM Plex Mono (Google Fonts)

### External Resources
- None (fully self-contained)

## 🧪 Testing

### Browser Compatibility
- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)
- Mobile browsers

### Responsive Testing
- Desktop (1920x1080, 1366x768)
- Tablet (768x1024)
- Mobile (375x667, 414x896)

## 📞 Support

For issues with the GitHub Pages site:
- Open an issue in the repository
- Contact: ecm-container-service@ibm.com

## 📄 License

Licensed Materials - Property of IBM

© Copyright IBM Corp. 2026. All Rights Reserved.

US Government Users Restricted Rights - Use, duplication or disclosure restricted by GSA ADP Schedule Contract with IBM Corp.