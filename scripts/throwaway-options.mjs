// The options of `npm run throwaway -- ...` (throwaway-metalist.mjs), parsed apart from the
// script so a unit test covers them (tests/unit/throwaway_options.test.mjs).

const OPTION_PREFIX = '--';
const FLAGS = ['--keep', '--empty', '--development'];
// Options taking a value, and the field each fills.
const VALUED = {'--notes': 'notes', '--files': 'files', '--scripted-ai': 'scriptedAi'};
const COUNTED = ['--notes', '--files'];
const WHOLE_NUMBER_ABOVE_ZERO = /^[1-9]\d*$/;
const USAGE = 'use --keep, --empty, --development, --notes N, --files N or --scripted-ai FILE';

export function parseThrowawayOptions(argv) {
  const options = {keep: false, empty: false, development: false, notes: null, files: null, scriptedAi: null};
  for (let index = 0; index < argv.length; index += 1) {
    const option = argv[index];
    if (FLAGS.includes(option)) {
      options[option.slice(OPTION_PREFIX.length)] = true;
      continue;
    }
    if (!(option in VALUED)) throw new Error(`Unknown option ${option}: ${USAGE}`);
    const value = argv[index + 1];
    if (value === undefined || value.startsWith(OPTION_PREFIX)) throw new Error(`${option} needs a value: ${USAGE}`);
    index += 1;
    if (COUNTED.includes(option)) {
      if (!WHOLE_NUMBER_ABOVE_ZERO.test(value)) throw new Error(`${option} needs a whole number above 0, got ${value}`);
      options[VALUED[option]] = Number(value);
    } else {
      options[VALUED[option]] = value;
    }
  }
  if (options.empty && (options.notes !== null || options.files !== null)) {
    throw new Error('--empty cannot be combined with --notes or --files');
  }
  if (options.files !== null && options.notes === null) throw new Error('--files needs --notes');
  return options;
}
