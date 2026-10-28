// The key a person holds for the browser's own shortcuts (copy, paste, undo): ⌘ on a Mac,
// Ctrl on Linux and Windows. MetaList answers either (keyboard-events.js), but the browser
// runs its own copy, paste or undo only for its platform's key: on Linux, Firefox pasted
// nothing for ⌘V, so the CI suites saw no paste (2026-10-28). Use it wherever a step needs
// the browser itself to copy, paste or undo.
export function commandKeyFor(platform) {
  if (platform === 'darwin') return 'Meta';
  return 'Control';
}

export const COMMAND_KEY = commandKeyFor(process.platform);
