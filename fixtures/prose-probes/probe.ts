// Routes under /api/* go to the services; this line comment must not open a block comment.
// cs-probe-ts-PROSE appears only in comments.
export const PATTERN = "/api/admin/*";
export const topic = (id: string) => `/orders/${encodeURIComponent(id)}/cs-probe-ts-CODE`;
/* cs-probe-ts-PROSE again, in a real block comment. */
