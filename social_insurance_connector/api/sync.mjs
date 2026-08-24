import { createPostHandler } from "../lib/http.mjs";
import { syncCandidates } from "../lib/service.mjs";

export default createPostHandler(syncCandidates);
