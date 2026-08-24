import { createPostHandler } from "../lib/http.mjs";
import { listSubjects } from "../lib/service.mjs";

export default createPostHandler(listSubjects);
