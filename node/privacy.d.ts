/** The SDK's privacy word rules, by public, stable names (@crowkis/client/privacy). */
/** A turn about the caller's own records, or otherwise never shared. */
export function isPersonal(text: string): boolean;
/** A turn that only means something next to the turn before it. */
export function isContextDependent(text: string): boolean;
/** An answer shape that still holds one of the caller's declared values. */
export function leaks(shaped: string, values: Record<string, string>): boolean;
/** An answer with the caller's declared values taken out ({slot} in their place). */
export function abstract(answer: string, values: Record<string, string>): string;
/** An answer shape filled with this caller's values, or null when a slot has no value. */
export function fill(shape: string, values: Record<string, string>): string | null;
/** A slot in an answer shape: {name}. */
export const SLOT: RegExp;
/** The similarity a follow-up or a short turn needs to match. */
export const CONTEXT_BOUND_THRESHOLD: number;
