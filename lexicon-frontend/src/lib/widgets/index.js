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
import TimerWidget from './TimerWidget.svelte';
import DateWidget from './DateWidget.svelte';
import NoteWidget from './NoteWidget.svelte';
import CalculatorWidget from './CalculatorWidget.svelte';
import SysMonWidget from './SysMonWidget.svelte';
import WeatherWidget from './WeatherWidget.svelte';
import HelpWidget from './HelpWidget.svelte';
import TerminalWidget from './TerminalWidget.svelte';
import WhatsAppWidget from './WhatsAppWidget.svelte';

const registry = {
  clock: ClockWidget,
  timer: TimerWidget,
  date: DateWidget,
  note: NoteWidget,
  calculator: CalculatorWidget,
  sysmon: SysMonWidget,
  weather: WeatherWidget,
  help: HelpWidget,
  terminal: TerminalWidget,
  whatsapp: WhatsAppWidget,
};

export default registry;
