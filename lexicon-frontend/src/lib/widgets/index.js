/**
 * Widget Registry
 *
 * Maps widget_type strings (sent by the backend) → Svelte components.
 * To add a new widget:
 *   1. Create WidgetName.svelte in this folder
 *   2. Import it here
 *   3. Add it to the registry object
 */

import ClockWidget from './ClockWidget.svelte';

const registry = {
  clock: ClockWidget,
};

export default registry;
