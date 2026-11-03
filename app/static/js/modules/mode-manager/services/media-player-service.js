import { FilesAPI } from '../../api-client.js';
import { rethrowUnexpectedError } from '../../expected-errors.js';

// Audio and video in the note (docs/ready-to-build/files-shown-not-copied.md §3; the maintainer,
// 2026-11-03): the note shows a Play button; Play loads the whole file, then plays it in the
// browser's own player. A file request needs the tab's header, which a player's own requests
// can't send, so the file comes as a blob first (no streaming). Nothing plays before Play.

const LOADING = 'loading';
const PLAYING = 'playing';
const MEDIA_ELEMENTS = { audio: 'audio', video: 'video' };

/** Load the file of the player holding playButton and play it there. */
export async function playMediaFile(playButton) {
    if (!(playButton instanceof HTMLElement)) {
        throw new Error('playMediaFile requires the Play button');
    }
    const embed = playButton.closest('.note-file-media-embed');
    if (!(embed instanceof HTMLElement)) {
        throw new Error('A Play button belongs to a player');
    }
    const fileId = embed.dataset.fileRefId;
    const mediaKind = embed.dataset.mediaKind;
    if (typeof fileId !== 'string' || fileId === '' || !Object.hasOwn(MEDIA_ELEMENTS, mediaKind)) {
        throw new Error('A player names its file and whether it is audio or video');
    }
    if (embed.dataset.mediaState !== 'idle') return;
    embed.dataset.mediaState = LOADING;
    playButton.disabled = true;
    const downloaded = await FilesAPI.downloadFile(fileId);
    const player = document.createElement(MEDIA_ELEMENTS[mediaKind]);
    player.className = 'note-file-media-player';
    player.controls = true;
    player.src = URL.createObjectURL(downloaded.blob);
    if (mediaKind === 'video') player.playsInline = true;
    playButton.replaceWith(player);
    embed.dataset.mediaState = PLAYING;
    // A file that took long to load may need a click of the browser's own (NotAllowedError):
    // its Play is there.
    await player.play().catch((error) => {
        rethrowUnexpectedError(error);
    });
}
