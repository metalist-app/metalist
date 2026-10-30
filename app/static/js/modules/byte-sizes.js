// Binary byte sizes by name, so a size reads as 16 * MIB rather than 16 * 1024 * 1024.

export const KIB = 1024;
export const MIB = KIB * KIB;
export const GIB = MIB * KIB;

// A size as people read it: 512 B, 1.5 KB, 3.0 MB.
export function formatByteSize(sizeBytes) {
    if (!Number.isInteger(sizeBytes) || sizeBytes < 0) {
        throw new Error('sizeBytes must be a non-negative integer');
    }
    if (sizeBytes < KIB) {
        return `${sizeBytes} B`;
    }
    if (sizeBytes < MIB) {
        return `${(sizeBytes / KIB).toFixed(1)} KB`;
    }
    if (sizeBytes < GIB) {
        return `${(sizeBytes / MIB).toFixed(1)} MB`;
    }
    return `${(sizeBytes / GIB).toFixed(1)} GB`;
}
