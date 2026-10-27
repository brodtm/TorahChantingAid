import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const http = axios.create({ baseURL: API, timeout: 60000 });

export const api = {
  health: () => http.get("/health").then(r => r.data),
  buildIndex: () => http.post("/index/build").then(r => r.data),
  getBooks: () => http.get("/torah/books").then(r => r.data),
  getParshiyot: () => http.get("/torah/parshiyot").then(r => r.data),
  getChapter: (book, chapter) => http.get(`/torah/chapter/${book}/${chapter}`).then(r => r.data),
  locate: (snippet, hint_book, hint_chapter, hint_category) =>
    http.post("/torah/locate", { snippet, hint_book, hint_chapter, hint_category }).then(r => r.data),
  getLines: (book, chapter, verse, context = 2) =>
    http.post("/torah/lines", { book, chapter, verse, context }).then(r => r.data),
  createSession: (name) => http.post("/sessions", { name }).then(r => r.data),
  getSession: (id) => http.get(`/sessions/${id}`).then(r => r.data),
  updateSession: (id, payload) => http.patch(`/sessions/${id}`, payload).then(r => r.data),
  saveCalibration: (payload) => http.post("/calibration", payload).then(r => r.data),
  getCalibration: (id) => http.get(`/calibration/${id}`).then(r => r.data),

  // Scroll profile / column-map endpoints
  listScrollProfiles: () => http.get("/scroll/profiles").then(r => r.data),
  getScrollProfile: (name) => http.get(`/scroll/profile/${name}`).then(r => r.data),
  getScrollColumn: (name, n) => http.get(`/scroll/${name}/column/${n}`).then(r => r.data),
  locateColumn: (snippet, profile = "tikkun_koreim") =>
    http.post("/scroll/locate-column", { snippet, profile }).then(r => r.data),
  scrollLineAt: (column, y_fraction, profile = "tikkun_koreim") =>
    http.post("/scroll/line-at", { column, y_fraction, profile }).then(r => r.data),
};
