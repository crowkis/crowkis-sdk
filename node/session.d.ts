// Types for @crowkis/client/session.
export { CallSession, CallSessionOptions, TurnResult } from "./index";
/** The route of a turn answered by a registered filler. */
export const FILLER: "filler";
/** The modes setMode() accepts. */
export const MODES: readonly ["full", "replay_only", "off"];
