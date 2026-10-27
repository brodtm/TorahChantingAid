import { createWorker } from "tesseract.js";

let _worker = null;
let _initPromise = null;

// Load Tesseract assets locally so the app works fully offline.
// `langPath`   -> /tessdata/heb.traineddata.gz (Hebrew language model)
// `workerPath` -> /tesseract/worker.min.js     (Tesseract worker JS)
// `corePath`   -> /tesseract/                   (folder containing the WASM core)
const PUB = process.env.PUBLIC_URL || "";
const LANG_PATH = `${PUB}/tessdata`;
const WORKER_PATH = `${PUB}/tesseract/worker.min.js`;
const CORE_PATH = `${PUB}/tesseract`;

export async function getOcrWorker() {
  if (_worker) return _worker;
  if (_initPromise) return _initPromise;
  _initPromise = (async () => {
    const w = await createWorker("heb", 1, {
      langPath: LANG_PATH,
      workerPath: WORKER_PATH,
      corePath: CORE_PATH,
      cacheMethod: "none",
      // logger: m => console.debug("[ocr]", m),
    });
    await w.setParameters({
      tessedit_pageseg_mode: "7",
      preserve_interword_spaces: "1",
    });
    _worker = w;
    return w;
  })();
  return _initPromise;
}

export async function ocrCanvas(canvas) {
  const w = await getOcrWorker();
  const { data } = await w.recognize(canvas);
  return { text: (data.text || "").trim(), confidence: data.confidence ?? 0 };
}

export async function terminateOcr() {
  if (_worker) {
    try {
      await _worker.terminate();
    } catch (e) {
      console.warn("[ocr] worker terminate failed:", e);
    }
    _worker = null;
    _initPromise = null;
  }
}
