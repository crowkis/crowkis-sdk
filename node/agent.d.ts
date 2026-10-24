// Types for @crowkis/client/agent.
export { Agent, AgentOptions, AskOptions, AskResult, AudioStats, RouteStats, ToolStats, CachedTool, Synthesise } from "./index";
/** Resolves once every audio clip handed to the background has been stored (for tests). */
export function waitForAudioStores(): Promise<void>;
/** Whether an error says the server has no Voice add-on. */
export function voiceAddonMissing(error: unknown): boolean;
