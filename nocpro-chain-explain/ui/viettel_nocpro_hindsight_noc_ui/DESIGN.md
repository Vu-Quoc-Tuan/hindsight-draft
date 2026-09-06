---
name: Viettel NocPro Hindsight NOC UI
colors:
  surface: '#0c1322'
  surface-dim: '#0c1322'
  surface-bright: '#323949'
  surface-container-lowest: '#070e1d'
  surface-container-low: '#141b2b'
  surface-container: '#191f2f'
  surface-container-high: '#232a3a'
  surface-container-highest: '#2e3545'
  on-surface: '#dce2f7'
  on-surface-variant: '#e4beba'
  inverse-surface: '#dce2f7'
  inverse-on-surface: '#293040'
  outline: '#ab8986'
  outline-variant: '#5b403e'
  surface-tint: '#ffb3ad'
  primary: '#ffb3ad'
  on-primary: '#68000a'
  primary-container: '#ff5451'
  on-primary-container: '#5c0008'
  inverse-primary: '#b91a24'
  secondary: '#7bd0ff'
  on-secondary: '#00354a'
  secondary-container: '#00a6e0'
  on-secondary-container: '#00374d'
  tertiary: '#ffb95f'
  on-tertiary: '#472a00'
  tertiary-container: '#ca8100'
  on-tertiary-container: '#3e2400'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#ffdad7'
  primary-fixed-dim: '#ffb3ad'
  on-primary-fixed: '#410004'
  on-primary-fixed-variant: '#930013'
  secondary-fixed: '#c4e7ff'
  secondary-fixed-dim: '#7bd0ff'
  on-secondary-fixed: '#001e2c'
  on-secondary-fixed-variant: '#004c69'
  tertiary-fixed: '#ffddb8'
  tertiary-fixed-dim: '#ffb95f'
  on-tertiary-fixed: '#2a1700'
  on-tertiary-fixed-variant: '#653e00'
  background: '#0c1322'
  on-background: '#dce2f7'
  surface-variant: '#2e3545'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: 0em
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: 0em
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0em
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0em
  code-lg:
    fontFamily: JetBrains Mono
    fontSize: 16px
    fontWeight: '500'
    lineHeight: 24px
    letterSpacing: 0em
  code-md:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: -0.01em
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.02em
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '700'
    lineHeight: 12px
    letterSpacing: 0.08em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  space-2xs: 2px
  space-xs: 4px
  space-sm: 8px
  space-md: 12px
  space-lg: 16px
  space-xl: 24px
  space-2xl: 32px
  gutter: 12px
  margin-screen: 16px
  panel-header-h: 36px
  row-compact-h: 28px
  row-standard-h: 36px
---

## Brand & Style

This design system is engineered specifically for mission-critical Network Operations Centers (NOC) and high-stress infrastructure monitoring environments operating 24/7/365. The operational narrative demands clinical precision, split-second anomaly detection, zero visual ambiguity, and minimum retinal fatigue over extended monitoring shifts.

The visual style merges **Technical Minimalism** with **High-Density Cybernetic Utility**:
- **Utilitarian & Grounded:** Eliminates decorative gradients, skeuomorphic noise, and diffuse shadows in favor of crisp 1px structural boundaries, structured tabular layouts, and purposeful luminance contrast.
- **Cognitive Clarity:** Information density is calibrated so network engineers can survey thousands of distributed interfaces, telemetry pipes, and alert queues across panoramic wall displays or local multi-monitor setups without cognitive overload.
- **Topology-Driven Semantics:** Visual hierarchy relies on strictly codified network tiering—CORE, BRIDGE, LEAF, and WEAK—allowing immediate triaging of link degradation, route flaps, and hardware failures.

## Colors

The palette operates entirely in a high-performance dark slate domain, tuned to prevent circadian disruption while ensuring AA/AAA contrast ratios for critical telemetry.

### Core Topology & Criticality Roles
- **CORE (`#EF4444` / Crimson Red):** Designated for Tier-0 core backbones, catastrophic route drops, transit link severances, and critical alerts. Demands immediate operator intervention.
- **BRIDGE (`#F59E0B` / Amber Orange):** Designated for aggregation switches, transport interconnects, latency threshold warnings, and degraded redundancy.
- **LEAF (`#38BDF8` / Sky Blue):** Designated for edge nodes, access points, customer-facing interfaces, and operational telemetry streams.
- **WEAK (`#C084FC` / Fuchsia Purple):** Designated for unverified BGP peers, low-confidence heuristic anomalies, jitter spikes, and non-deterministic packet loss.

### Surface Architecture & Foundations
- **Base Abyss (`#0B0F19`):** Application root canvas, backdrop for wall monitors and edge-to-edge NOC views.
- **Surface Elevation 1 (`#111827`):** Standard panel, card, and telemetry rack background.
- **Surface Elevation 2 (`#1F2937`):** Active table rows, floating modals, utility drawers, and inspector sidebars.
- **Structural Outlines (`#374151`):** Subdued borders and grid dividers.
- **Active / Focused Borders (`#4B5563`):** Interactive boundaries and highlighted modules.

### Status Indicators
- **Nominal / OK (`#10B981`):** Healthy packet flow, validated state, synced telemetry.
- **Muted Text (`#9CA3AF`):** Secondary metadata, inactive states, unit notations.
- **Primary Text (`#F9FAFB`):** Dynamic values, primary identifiers, active readings.

## Typography

Typography is split strictly into two functional disciplines: **Structural Prose** (`Inter`) and **Operational Telemetry** (`JetBrains Mono`).

### Discipline Breakdown
- **UI & Structural Controls (Inter):** Applied across all high-level navigation, table headers, form inputs, modal dialogs, and analytical summaries. Inter provides neutral readability without drawing attention away from visual status codes.
- **Telemetry, System Identifiers & Metrics (JetBrains Mono):** Mandatory for IPv4/IPv6 addresses, MAC addresses, Autonomous System Numbers (ASNs), interface indices (e.g., `xe-0/0/1.0`), timestamps (ISO 8601 / UTC epoch), throughput metrics (`Gbps`, `Mpps`), and stack traces. Monospacing preserves vertical alignment in high-density data tables and real-time counter fields.

### Hierarchy & Style Rules
- All machine-facing metadata attributes use `label-caps` with uppercase transformation.
- Numerical readouts in tabular rows must use tabular figures (`font-variant-numeric: tabular-nums`) to prevent horizontal jitter during rapid real-time updates.

## Layout & Spacing

The layout philosophy follows a **Dense Modular Grid** optimized for high-resolution 1440p, 4K, and ultra-wide NOC arrays.

### Grid & Density
- Standard density uses an **8px structural grid** with an internal **4px micro-increment** for data rows, telemetry bars, and status pills.
- Standard dashboard configurations leverage a **24-column fluid layout** with `12px` gutters to accommodate complex split-views (e.g., Network Map 16 cols, Incident Stream 8 cols).
- Vertical rhythms are strictly budgeted: panel headers lock to `36px`, compact telemetry rows lock to `28px`, and standard data rows lock to `36px` to ensure uniform vertical scannability across adjacent panels.

### Responsive Breakpoints & Viewport Reflow
- **Monitor Wall / 4K (`>= 2560px`):** Quad-column layout with pinned global topology canvas, real-time alert waterfall, and persistent metric inspectors.
- **Desktop Workstation (`1440px - 2559px`):** Dual or triple column; collapsible inspection drawer; pinned top-level global alert bar.
- **Field Terminal / Laptop (`1024px - 1439px`):** Single dashboard column with tabbed secondary views; drawers switch to full-height overlay sheets.
- **Emergency Mobile (`< 1024px`):** Linear alert stack; tables convert to key-value card arrays; telemetry graphs collapse to sparklines.

## Elevation & Depth

This design system deliberately eschews soft drop shadows and diffuse blurs. In a multi-display NOC environment, diffuse shadows reduce contrast, create visual murkiness, and slow down rendering engines during rapid canvas redrawing.

### Low-Contrast Outlines & Tonal Stacking
- **Depth Tier 0 (Background):** Solid `#0B0F19`. Canvas level for root layout.
- **Depth Tier 1 (Panels & Cards):** Solid `#111827` encapsulated by a 1px border of `#1F2937` or `#374151`.
- **Depth Tier 2 (Flyouts & Popovers):** Solid `#1F2937` with a 1px border of `#4B5563` and a tight ambient drop shadow (`box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5)`).
- **Active State Highlights:** Active or focused panels drop a hard, high-contrast 1px border in the role color (e.g., `1px solid #EF4444` when inspecting a degraded CORE node).

### Layering via Dividers
- Content divisions within the same panel rely on 1px solid hairline dividers (`#1F2937` or `#374151`) rather than margin gaps, preserving screen real estate.

## Shapes

The design system enforces a precise, geometric shape language configured at **Level 1 (Soft / Technical)**:
- **Panels, Cards, and Modals:** `4px` (`rounded-sm`). Clean, functional, and efficient with zero wasted pixel real estate at border corners.
- **Buttons, Form Inputs, and Dropdowns:** `4px` (`rounded-sm`).
- **Telemetry Badges and Status Pills:** `2px` or `4px` (`rounded-sm`). Fully rounded pill shapes are avoided to preserve the rigorous, instrumentation-grade feel.
- **Graph Nodes & Connectors:** Rectilinear with 90-degree orthogonal routing lines.

## Components

### Buttons
- **Primary / Action:** Background `#EF4444` (or role-specific), text `#FFFFFF`, 1px border in matching tone, hover brightness `110%`, active scale `0.98`. Height `32px`, font `Inter` 13px weight 600.
- **Secondary / Technical:** Background `#1F2937`, text `#F9FAFB`, border `1px solid #374151`, hover background `#374151`.
- **Ghost / Tool:** Borderless, background transparent, text `#9CA3AF`, hover text `#F9FAFB`, hover background `#1F2937`.

### Telemetry Pills & Role Badges
- **Architecture:** Monospace typography (`JetBrains Mono` 11px), uppercase, height `20px`, padding `0 6px`.
- **Tokens:**
  - **CORE:** Background `rgba(239, 68, 68, 0.15)`, text `#EF4444`, border `1px solid rgba(239, 68, 68, 0.4)`.
  - **BRIDGE:** Background `rgba(245, 158, 11, 0.15)`, text `#F59E0B`, border `1px solid rgba(245, 158, 11, 0.4)`.
  - **LEAF:** Background `rgba(56, 189, 248, 0.15)`, text `#38BDF8`, border `1px solid rgba(56, 189, 248, 0.4)`.
  - **WEAK:** Background `rgba(192, 132, 252, 0.15)`, text `#C084FC`, border `1px solid rgba(192, 132, 252, 0.4)`.

### Technical Cards & Panels
- **Structure:** Background `#111827`, border `1px solid #1F2937`. Header height `36px` with bottom border `1px solid #1F2937`.
- **Header Pattern:** Title on left in `Inter` 13px bold, trailing contextual actions (status dot, counter, icon button) aligned to the right margin.

### Data Tables (NOC Matrix)
- **Cell Layout:** Compact `28px` or standard `36px` row height.
- **Header:** Background `#0B0F19`, text `#9CA3AF`, `label-caps` styling, uppercase, no wrap.
- **Rows:** Alternate row striping optional; default uses border-bottom `1px solid #1F2937`. Hover state highlights entire row with background `#1F2937`.
- **Alignment:** Strings left-aligned (`Inter`), IP/MAC/Metrics right-aligned (`JetBrains Mono`).

### Input Fields
- **Base Style:** Height `32px`, background `#0B0F19`, border `1px solid #374151`, text `#F9FAFB`, font `JetBrains Mono` 12px for CLI/query inputs or `Inter` 13px for general metadata.
- **Focus:** 1px ring `#38BDF8` with border `#38BDF8`.

### Checkboxes & Switches
- **Checkbox:** `14px x 14px`, 2px radius, background `#0B0F19`, border `1px solid #4B5563`. Checked state fills with `#38BDF8` displaying a sharp white tick.
- **Toggle Switch:** Rectangular `28px x 16px`, track `#1F2937`, thumb `12px x 12px` square with 1px radius.

### Specialized NOC Elements
- **Telemetry Sparkline:** Single-line vector rendering embedded directly into table cells without axis labels.
- **Ping / Jitter Pulse:** Concentric ping animation on topological node failure: 4px dot with an expanding ping ring keyed to the status color (`#EF4444` for core drops).