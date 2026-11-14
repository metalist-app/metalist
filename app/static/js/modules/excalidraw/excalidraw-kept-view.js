// The view a diagram file keeps, recorded in the editor session after each save.
import { stateValuesEqual } from '../application-state.js';

// Saves without panning or zooming write the view the session already keeps; that is no change.
export function keepSavedView(session, view) {
    if (stateValuesEqual(session.keptView, view)) {
        return;
    }
    session.keptView = view;
}
