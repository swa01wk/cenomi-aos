import type { components } from "../api/schema";

export type Stage = components["schemas"]["Stage"];
export type Turn = components["schemas"]["Turn"];
export type Block = components["schemas"]["Block"];
export type ToolActivity = components["schemas"]["ToolActivity"];
export type MessageDelta = components["schemas"]["MessageDelta"];
export type SeatState = components["schemas"]["SeatState"];
export type PublishRequestPart = components["schemas"]["PublishRequest"]["parts"][number];
