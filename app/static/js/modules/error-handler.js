/**
 * Error Handler - Centralized error handling for authentication and network errors
 */

import { parseDecimalInteger } from './decimal-integer.js';
import { ModeContextInstance as ModeContext } from './mode-manager/mode-context.js';
import { Auth } from './auth.js';
import { classifyApiFailure } from './api-failure-classification-service.js';
import { clearEditingStateForDisconnect } from './disconnect-editing-state-service.js';
import { MS_PER_SECOND } from './time-units.js';
import { FloatingMessages } from './floating-messages.js';

const RESTORE_TRANSITION_UNTIL_KEY = 'metalist_restore_transition_until_ms';
const HTTP_ERROR_BANNER_SECONDS = 5;
const CONNECTION_CARD_KEY = 'connection';
const CONNECTION_LOST_TEXT = 'Not saved, reconnecting…';
const RECONNECTED_TEXT = 'Reconnected';
const CONNECTION_ESCALATION_TEXT = "MetaList can't reach its server. Changes can't be saved until it's back; MetaList keeps trying.";


function _isRestoreTransitionActive() {
    const rawValue = sessionStorage.getItem(RESTORE_TRANSITION_UNTIL_KEY);
    if (rawValue === null) {
        return false;
    }
    if (!/^[0-9]+$/.test(rawValue)) {
        sessionStorage.removeItem(RESTORE_TRANSITION_UNTIL_KEY);
        return false;
    }
    const untilMs = parseDecimalInteger(rawValue);
    if (!Number.isInteger(untilMs)) {
        sessionStorage.removeItem(RESTORE_TRANSITION_UNTIL_KEY);
        return false;
    }
    if (Date.now() >= untilMs) {
        sessionStorage.removeItem(RESTORE_TRANSITION_UNTIL_KEY);
        return false;
    }
    return true;
}

export const ErrorHandler = {
    
    /**
     * Handle different types of API errors with appropriate UX
     */
    handleApiError(error, response) {
        console.error('[ErrorHandler] Handling API failure');

        const failure = classifyApiFailure(error, response);
        if (failure.kind === 'auth') {
            this.handleAuthError(failure.message);
            return;
        }
        if (failure.kind === 'http') {
            this.handleHttpError(failure.message);
            return;
        }
        if (failure.kind === 'network') {
            this.handleNetworkError(failure.message);
            return;
        }
        if (failure.kind === 'internal') {
            throw failure.error;
        }
        throw new Error(`Unsupported API failure kind: ${failure.kind}`);
    },
    
    /**
     * Handle authentication errors (401) - show login screen
     */
    handleAuthError(message) {
        if (typeof message !== 'string' || message.length === 0) {
            throw new Error('ErrorHandler.handleAuthError requires message string');
        }
        console.log('[ErrorHandler] Authentication error');
        Auth.forceLogout(message);
    },

    /**
     * Report an HTTP application failure without claiming the connection was lost.
     */
    handleHttpError(message) {
        if (typeof message !== 'string' || message.length === 0) {
            throw new Error('ErrorHandler.handleHttpError requires message string');
        }
        console.log('[ErrorHandler] HTTP error');
        this.showErrorBanner(message, 'error', HTTP_ERROR_BANNER_SECONDS * MS_PER_SECOND, { closable: true });
    },
    
    /**
     * Handle network errors - show a calm lasting card but keep the interface visible
     */
    handleNetworkError(message) {
        if (typeof message !== 'string' || message.length === 0) {
            throw new Error('ErrorHandler.handleNetworkError requires message string');
        }
        if (_isRestoreTransitionActive()) {
            console.log('[ErrorHandler] Suppressed network error during restore transition');
            return;
        }
        console.log('[ErrorHandler] Network error');
        
        // Check if we're already showing the connection card
        if (!ModeContext.connectionErrorBannerVisible) {
            // First network error - show banner and set disconnected state
            if (ModeContext.isConnected) {
                ModeContext.setConnected(false);
            }
            ModeContext.setConnectionErrorBannerVisible(true);
            // The card stays as long as the connection is lost; the reason is its tooltip.
            FloatingMessages.show({
                text: CONNECTION_LOST_TEXT,
                type: 'connection',
                detail: message,
                isClosable: false,
                isLasting: true,
                key: CONNECTION_CARD_KEY,
            });
            FloatingMessages.escalateAfter(CONNECTION_CARD_KEY, CONNECTION_ESCALATION_TEXT);
            this.disableEditingUI();
        }
        // If the card is already showing, don't create a new one
    },
    
    /**
     * Handle successful connection - replace the connection card with "Reconnected"
     */
    handleConnectionRestored() {
        // Only process if we were actually disconnected
        if (!ModeContext.isConnected || ModeContext.connectionErrorBannerVisible) {
            console.log('[ErrorHandler] Connection restored');
            
            if (!ModeContext.isConnected) {
                ModeContext.setConnected(true);
            }
            
            if (ModeContext.connectionErrorBannerVisible) {
                ModeContext.setConnectionErrorBannerVisible(false);
                FloatingMessages.endEscalation(CONNECTION_CARD_KEY);
                FloatingMessages.replace(CONNECTION_CARD_KEY, {
                    text: RECONNECTED_TEXT,
                    type: 'success',
                    detail: '',
                    isClosable: false,
                    isLasting: false,
                    key: null,
                });
                this.enableEditingUI();
            }
        }
        // If already connected, do nothing silently
    },
    
    /**
     * Disable all contenteditable elements when disconnected
     */
    disableEditingUI() {
        // Find all potentially editable elements (both active and inactive)
        const editableElements = document.querySelectorAll('.note-content');
        
        editableElements.forEach(element => {
            // Save original state
            if (element.getAttribute('contenteditable') === 'true') {
                element.setAttribute('data-was-contenteditable', 'true');
            }
            
            // Disable editing and apply disconnected styling
            element.setAttribute('contenteditable', 'false');
            element.classList.add('disconnected-state');
            element.style.cursor = 'not-allowed';
            element.style.opacity = '0.7';
            element.style.pointerEvents = 'none'; // Prevent any interaction
        });
        
        // Exit edit mode immediately without server calls if currently editing.
        // currentContent can still be null while note selection awaits its first refresh.
        if (clearEditingStateForDisconnect(ModeContext)) {
            console.log('[ErrorHandler] Force-exited edit mode due to disconnection');
        }
    },
    
    /**
     * Re-enable contenteditable elements when connection restored
     */
    enableEditingUI() {
        // Re-enable all note content elements
        document.querySelectorAll('.note-content.disconnected-state').forEach(element => {
            // Remove disconnected styling
            element.classList.remove('disconnected-state');
            element.style.cursor = '';
            element.style.opacity = '';
            element.style.pointerEvents = '';
            
            // Restore contenteditable state if it was previously editable
            if (element.getAttribute('data-was-contenteditable') === 'true') {
                element.removeAttribute('data-was-contenteditable');
                // Don't set contenteditable back to true - let the app manage that
            } else {
                // Make sure it's set to false for non-editing elements
                element.setAttribute('contenteditable', 'false');
            }
        });
    },
    
    /**
     * Show a lasting floating message (no timer, no close button)
     */
    showPersistentErrorBanner(message, type) {
        if (typeof type !== 'string' || type.length === 0) {
            throw new Error('ErrorHandler.showPersistentErrorBanner requires type string');
        }
        this.showErrorBanner(message, type, 0, { closable: false }); // duration 0: lasting
    },
    
    /**
     * Show a floating message in the upper-right corner (floating-messages.js).
     */
    // duration 0 makes a lasting card; any other asks for a passing one, whose time on
    // screen follows the floating-messages rule (news 4–10 s, errors 10 s).
    // options.closable: whether the card shows a × to close it.
    showErrorBanner(message, type, duration, options) {
        if (typeof message !== 'string' || message.length === 0) {
            throw new Error('ErrorHandler.showErrorBanner requires message string');
        }
        if (typeof type !== 'string' || type.length === 0) {
            throw new Error('ErrorHandler.showErrorBanner requires type string');
        }
        if (typeof duration !== 'number' || duration < 0) {
            throw new Error('ErrorHandler.showErrorBanner requires duration number');
        }
        if (!options || typeof options !== 'object' || typeof options.closable !== 'boolean') {
            throw new Error('ErrorHandler.showErrorBanner requires options.closable boolean');
        }
        FloatingMessages.show({
            text: message,
            type,
            detail: '',
            isClosable: options.closable,
            isLasting: duration === 0,
            key: null,
        });
    },
    
    /**
     * Hide every floating message
     */
    hideErrorBanner() {
        FloatingMessages.dismissAll();
    },
    
    /**
     * Show success message banner
     */
    showSuccessBanner(message, duration) {
        if (typeof duration !== 'number') {
            throw new Error('ErrorHandler.showSuccessBanner requires duration number');
        }
        this.showErrorBanner(message, 'success', duration, { closable: false });
    },
    
    /**
     * Show info message banner  
     */
    showInfoBanner(message, duration) {
        if (typeof duration !== 'number') {
            throw new Error('ErrorHandler.showInfoBanner requires duration number');
        }
        this.showErrorBanner(message, 'info', duration, { closable: false });
    }
};

// Make available globally
window.ErrorHandler = ErrorHandler;
