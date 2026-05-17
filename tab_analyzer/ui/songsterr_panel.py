"""Embedded Songsterr page panel."""

from __future__ import annotations

from .common import *

class SongsterrPagePanel(QWidget):
    playbackPositionChanged = pyqtSignal(object)

    _STAGE_BRIDGE_SCRIPT = """
(function () {
    try {
        Object.defineProperty(window, "__STAGE__", {
            get: function () { return "tab-analyzer"; },
            set: function () {},
            configurable: false
        });
        window.__TAB_ANALYZER_SONGSTERR__ = true;
    } catch (error) {}
})();
"""

    _AD_CLEANUP_SCRIPT = r"""
(function () {
    if (window.__TAB_ANALYZER_SONGSTERR_AD_CLEANUP__) {
        return;
    }
    window.__TAB_ANALYZER_SONGSTERR_AD_CLEANUP__ = true;

    const STYLE_ID = "tab-analyzer-songsterr-ad-cleanup-style";
    const AD_HOST_PATTERN = /(2mdn\.net|aaxads\.com|adform\.net|adnxs\.com|adsafeprotected\.com|adsrvr\.org|adservice\.google\.com|amazon-adsystem\.com|casalemedia\.com|criteo\.com|criteo\.net|doubleclick\.net|fundingchoicesmessages\.google\.com|googlesyndication\.com|googletagmanager\.com|googletagservices\.com|imasdk\.googleapis\.com|lijit\.com|media\.net|moatads\.com|openx\.net|outbrain\.com|pubmatic\.com|quantserve\.com|rubiconproject\.com|scorecardresearch\.com|smartadserver\.com|taboola\.com|yieldmo\.com)/i;
    const AD_TOKEN_PATTERN = /(^|[\s_-])(ad|ads|advert|advertisement|adslot|ad-unit|adunit|ad-container|adcontainer|ad-banner|adbanner|gpt-ad|adsbygoogle|google-auto-placed)([\s_-]|$)/i;
    const AD_IFRAME_SELECTOR = [
        'iframe[src*="2mdn.net"]',
        'iframe[src*="adform.net"]',
        'iframe[src*="adnxs.com"]',
        'iframe[src*="adsafeprotected.com"]',
        'iframe[src*="adsrvr.org"]',
        'iframe[src*="amazon-adsystem.com"]',
        'iframe[src*="criteo.com"]',
        'iframe[src*="doubleclick.net"]',
        'iframe[src*="googlesyndication.com"]',
        'iframe[src*="googletagservices.com"]',
        'iframe[src*="openx.net"]',
        'iframe[src*="pubmatic.com"]',
        'iframe[src*="rubiconproject.com"]',
        'iframe[src*="smartadserver.com"]'
    ].join(',');
    const HIDE_SELECTOR = [
        'ins.adsbygoogle',
        '.adsbygoogle',
        '.google-auto-placed',
        '[id^="google_ads_iframe_"]',
        '[id*="div-gpt-ad"]',
        '[data-ad-client]',
        '[data-ad-slot]',
        AD_IFRAME_SELECTOR,
        '.video-ads',
        '.ytp-ad-image-overlay',
        '.ytp-ad-module',
        '.ytp-ad-overlay-container',
        '.ytp-ad-player-overlay',
        '.ytp-ad-text-overlay'
    ].join(',');
    const PROTECTED_SELECTOR = [
        '#apptab',
        '#tablature',
        '#tablist'
    ].join(',');
    const COLLAPSED_STYLE_PROPS = [
        "display",
        "visibility",
        "opacity",
        "pointer-events",
        "width",
        "height",
        "min-width",
        "min-height",
        "max-width",
        "max-height",
        "margin",
        "padding",
        "border",
        "overflow"
    ];
    const COLLAPSE_CSS = `
${HIDE_SELECTOR} {
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    width: 0 !important;
    height: 0 !important;
    min-width: 0 !important;
    min-height: 0 !important;
    max-width: 0 !important;
    max-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    overflow: hidden !important;
}
`;

    function installStyle() {
        const root = document.head || document.documentElement;
        if (!root || document.getElementById(STYLE_ID)) {
            return;
        }
        const style = document.createElement("style");
        style.id = STYLE_ID;
        style.textContent = COLLAPSE_CSS;
        root.appendChild(style);
    }

    function attrString(element) {
        if (!element) {
            return "";
        }
        const className = typeof element.className === "string"
            ? element.className
            : String(element.getAttribute("class") || "");
        return [
            element.id,
            className,
            element.getAttribute("aria-label"),
            element.getAttribute("data-ad-client"),
            element.getAttribute("data-ad-format"),
            element.getAttribute("data-ad-slot"),
            element.getAttribute("data-google-query-id")
        ].filter(Boolean).join(" ");
    }

    function srcLooksLikeAd(element) {
        const src = String(
            element.getAttribute("src")
            || element.getAttribute("data-src")
            || element.getAttribute("href")
            || ""
        );
        return AD_HOST_PATTERN.test(src);
    }

    function hasAdToken(element) {
        return AD_TOKEN_PATTERN.test(attrString(element));
    }

    function containsAdFrame(element) {
        try {
            return !!element.querySelector(AD_IFRAME_SELECTOR);
        } catch (error) {
            return false;
        }
    }

    function isProtectedSongsterrContent(element) {
        if (!element) {
            return false;
        }
        try {
            return !!(
                element.closest(PROTECTED_SELECTOR)
                || (element.matches(PROTECTED_SELECTOR))
                || element.querySelector(PROTECTED_SELECTOR)
            );
        } catch (error) {
            return false;
        }
    }

    function isBottomAdSlot(element) {
        if (!element || element === document.body || element === document.documentElement) {
            return false;
        }
        const rect = element.getBoundingClientRect();
        if (!rect || rect.width < 20 || rect.height < 12 || rect.height > window.innerHeight * 0.5) {
            return false;
        }
        const style = window.getComputedStyle(element);
        const isAnchored = style.position === "fixed" || style.position === "sticky";
        const isNearBottom = rect.top >= window.innerHeight * 0.45 || Math.abs(window.innerHeight - rect.bottom) <= 180;
        return isAnchored && isNearBottom && (hasAdToken(element) || containsAdFrame(element));
    }

    function collapseElement(element) {
        if (!element || element === document.body || element === document.documentElement || isProtectedSongsterrContent(element)) {
            return;
        }
        element.setAttribute("data-tab-analyzer-ad-hidden", "1");
        element.style.setProperty("display", "none", "important");
        element.style.setProperty("visibility", "hidden", "important");
        element.style.setProperty("opacity", "0", "important");
        element.style.setProperty("pointer-events", "none", "important");
        element.style.setProperty("width", "0", "important");
        element.style.setProperty("height", "0", "important");
        element.style.setProperty("min-width", "0", "important");
        element.style.setProperty("min-height", "0", "important");
        element.style.setProperty("max-width", "0", "important");
        element.style.setProperty("max-height", "0", "important");
        element.style.setProperty("margin", "0", "important");
        element.style.setProperty("padding", "0", "important");
        element.style.setProperty("border", "0", "important");
        element.style.setProperty("overflow", "hidden", "important");
    }

    function adRootFor(element) {
        let root = element;
        for (let depth = 0; depth < 4; depth += 1) {
            const parent = root && root.parentElement;
            if (!parent || parent === document.body || parent === document.documentElement) {
                break;
            }
            if (isProtectedSongsterrContent(parent)) {
                break;
            }
            const rect = parent.getBoundingClientRect();
            const compactWrapper = rect.height <= 360 && rect.width <= Math.max(window.innerWidth, 720)
                && (parent.children.length <= 4 || hasAdToken(parent) || containsAdFrame(parent));
            if (hasAdToken(parent) || parent.matches(".adsbygoogle, .google-auto-placed") || compactWrapper) {
                root = parent;
                continue;
            }
            break;
        }
        return root || element;
    }

    function hide(element) {
        const root = adRootFor(element);
        if (!isProtectedSongsterrContent(root)) {
            collapseElement(root);
        }
    }

    function restoreCollapsedElement(element) {
        if (!element || element === document.body || element === document.documentElement) {
            return;
        }
        if (element.getAttribute("data-tab-analyzer-ad-hidden") !== "1") {
            return;
        }
        element.removeAttribute("data-tab-analyzer-ad-hidden");
        COLLAPSED_STYLE_PROPS.forEach((property) => {
            element.style.removeProperty(property);
        });
    }

    function restoreProtectedContent() {
        try {
            document.querySelectorAll(PROTECTED_SELECTOR).forEach((protectedElement) => {
                let current = protectedElement;
                while (current && current !== document.body && current !== document.documentElement) {
                    restoreCollapsedElement(current);
                    current = current.parentElement;
                }
                protectedElement.querySelectorAll('[data-tab-analyzer-ad-hidden="1"]').forEach(restoreCollapsedElement);
            });
        } catch (error) {}
    }

    function cleanupAds() {
        installStyle();
        try {
            document.querySelectorAll(HIDE_SELECTOR).forEach(hide);
            document.querySelectorAll("iframe, ins, aside, section, div").forEach((element) => {
                if (srcLooksLikeAd(element) || hasAdToken(element) || containsAdFrame(element) || isBottomAdSlot(element)) {
                    hide(element);
                }
            });
            restoreProtectedContent();
        } catch (error) {}
    }

    let cleanupScheduled = false;
    function scheduleCleanup() {
        if (cleanupScheduled) {
            return;
        }
        cleanupScheduled = true;
        window.setTimeout(() => {
            cleanupScheduled = false;
            cleanupAds();
        }, 80);
    }

    cleanupAds();
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", cleanupAds, { once: true });
    }
    window.addEventListener("load", cleanupAds, { once: true });
    try {
        const observerRoot = document.documentElement || document;
        new MutationObserver(scheduleCleanup).observe(observerRoot, { childList: true, subtree: true, attributes: true });
    } catch (error) {}
})();
"""

    _PLAYBACK_STATE_SCRIPT = """
(function () {
    const store = window.__store__;
    if (!store || typeof store.get !== "function") {
        return { available: false, reason: "store" };
    }
    const state = store.get();
    const cursorState = state && state.cursor && state.cursor.position;
    const part = state && state.part && state.part.current;
    const measures = part && Array.isArray(part.measures) ? part.measures : [];
    const player = state && state.player ? state.player : {};
    const shouldPlay = !!player.shouldPlay || !!(player.instance && player.instance.isPlaying);
    if (!cursorState || !measures.length) {
        return {
            available: false,
            reason: "part",
            shouldPlay: shouldPlay
        };
    }
    let cursorValue = cursorState.cursor;
    if (player && player.instance && typeof player.instance.getCursor === "function") {
        const liveCursor = player.instance.getCursor();
        if (Number.isFinite(Number(liveCursor))) {
            cursorValue = liveCursor;
        }
    }
    const cursor = Number(cursorValue);
    if (!Number.isFinite(cursor)) {
        return { available: false, reason: "cursor", shouldPlay: shouldPlay };
    }
    const layoutPlaybackState = function (position) {
        for (let measureIndex = 0; measureIndex < measures.length; measureIndex += 1) {
            const measure = measures[measureIndex];
            const layouts = Array.isArray(measure && measure.layouts) ? measure.layouts : [];
            const beatLayouts = [];
            for (const layout of layouts) {
                const items = Array.isArray(layout && layout.beatsLayouts) ? layout.beatsLayouts : [];
                for (const item of items) {
                    if (!item || item.isAddable) {
                        continue;
                    }
                    const duration = Number(item.duration);
                    const occurrences = Array.isArray(item.occurrences) ? item.occurrences : [];
                    if (!Number.isFinite(duration) || duration <= 0 || duration > 3600000 || !occurrences.length) {
                        continue;
                    }
                    beatLayouts.push({ item: item, duration: duration, occurrences: occurrences });
                }
            }
            if (!beatLayouts.length) {
                continue;
            }
            const occurrenceCount = Math.max(...beatLayouts.map((beat) => beat.occurrences.length));
            for (let occurrenceIndex = 0; occurrenceIndex < occurrenceCount; occurrenceIndex += 1) {
                const firstBeat = beatLayouts[0];
                const lastBeat = beatLayouts[beatLayouts.length - 1];
                const start = Number(firstBeat.occurrences[Math.min(occurrenceIndex, firstBeat.occurrences.length - 1)]);
                const lastStart = Number(lastBeat.occurrences[Math.min(occurrenceIndex, lastBeat.occurrences.length - 1)]);
                const end = lastStart + lastBeat.duration;
                if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
                    continue;
                }
                if (position >= start && position < end) {
                    return {
                available: true,
                measureIndex: measureIndex,
                ratio: Math.max(0, Math.min(0.999999, (position - start) / (end - start))),
                cursor: position,
                shouldPlay: shouldPlay,
                speed: Number(player.speed) || 100,
                source: "layout"
            };
                }
            }
        }
        return null;
    };
    const durationUnits = function (duration) {
        if (!Array.isArray(duration) || duration.length < 2) {
            return 0;
        }
        const numerator = Number(duration[0]);
        const denominator = Number(duration[1]);
        if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator === 0) {
            return 0;
        }
        return Math.max(0, (4 * 960 * numerator) / denominator);
    };
    const measureLength = function (measure, signature) {
        const nextSignature = Array.isArray(measure && measure.signature) ? measure.signature : signature;
        const voices = Array.isArray(measure && measure.voices) ? measure.voices : [];
        let longest = 0;
        for (const voice of voices) {
            const beats = Array.isArray(voice && voice.beats) ? voice.beats : [];
            let total = 0;
            for (const beat of beats) {
                total += durationUnits(beat && beat.duration);
            }
            if (total > longest) {
                longest = total;
            }
        }
        if (longest > 0) {
            return { length: longest, signature: nextSignature };
        }
        const numerator = Number(nextSignature && nextSignature[0]) || 4;
        const denominator = Number(nextSignature && nextSignature[1]) || 4;
        return { length: Math.max(1, (4 * 960 * numerator) / denominator), signature: nextSignature };
    };
    const tempoAtMeasure = function (measureIndex) {
        const automations = part && part.automations && Array.isArray(part.automations.tempo)
            ? part.automations.tempo
            : [];
        let bpm = 120;
        for (const automation of automations) {
            const automationMeasure = Number(automation && automation.measure);
            const automationBpm = Number(automation && automation.bpm);
            if (Number.isFinite(automationMeasure) && automationMeasure <= measureIndex && Number.isFinite(automationBpm) && automationBpm > 0) {
                bpm = automationBpm;
            }
        }
        return bpm;
    };
    const measureDurationMs = function (measure, signature, measureIndex) {
        const current = measureLength(measure, signature);
        const bpm = tempoAtMeasure(measureIndex);
        return {
            duration: (current.length / 960) * (60000 / bpm),
            signature: current.signature
        };
    };
    const beatStartRatio = function (measure, voiceIndex, beatIndex, signature) {
        const current = measureLength(measure, signature);
        const length = Math.max(1, current.length);
        const voices = Array.isArray(measure && measure.voices) ? measure.voices : [];
        const voice = voices[Math.max(0, voiceIndex)] || voices[0];
        const beats = Array.isArray(voice && voice.beats) ? voice.beats : [];
        let start = 0;
        const end = Math.max(0, Math.min(beatIndex, beats.length));
        for (let index = 0; index < end; index += 1) {
            start += durationUnits(beats[index] && beats[index].duration);
        }
        return Math.max(0, Math.min(0.999999, start / length));
    };
    const editorCursor = state && state.editorUI && Array.isArray(state.editorUI.cursor)
        && Array.isArray(state.editorUI.cursor[0])
        ? state.editorUI.cursor[0]
        : null;
    if (!shouldPlay && editorCursor) {
        const editorMeasureIndex = Number(editorCursor[1]);
        if (Number.isInteger(editorMeasureIndex) && editorMeasureIndex >= 0 && editorMeasureIndex < measures.length) {
            const editorVoiceIndex = Number.isInteger(Number(editorCursor[2])) ? Number(editorCursor[2]) : 0;
            const editorBeatIndex = Number.isInteger(Number(editorCursor[3])) ? Number(editorCursor[3]) : 0;
            return {
                available: true,
                measureIndex: editorMeasureIndex,
                ratio: beatStartRatio(measures[editorMeasureIndex], editorVoiceIndex, editorBeatIndex, [4, 4]),
                cursor: cursor,
                shouldPlay: shouldPlay,
                speed: Number(player.speed) || 100,
                source: "editor"
            };
        }
    }
    if (shouldPlay) {
        const layoutState = layoutPlaybackState(cursor);
        if (layoutState) {
            return layoutState;
        }
    }
    let signature = [4, 4];
    let start = 0;
    const position = Math.max(0, cursor);
    for (let index = 0; index < measures.length; index += 1) {
        const current = measureDurationMs(measures[index], signature, index);
        signature = current.signature;
        const length = Math.max(1, current.duration);
        const isLast = index === measures.length - 1;
        if (position < start + length || isLast) {
            const ratio = Math.max(0, Math.min(0.999999, (position - start) / length));
            return {
                available: true,
                measureIndex: index,
                ratio: ratio,
                cursor: position,
                shouldPlay: shouldPlay,
                speed: Number(player.speed) || 100,
                source: "timeline"
            };
        }
        start += length;
    }
    return { available: false, reason: "range", shouldPlay: shouldPlay };
})();
"""

    def __init__(self) -> None:
        super().__init__()
        self._url = ""
        self._web_profile = None
        self._ad_request_interceptor = None
        self.view = None
        self._poll_in_flight = False
        self._last_state_key: tuple[int, int, bool] | None = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(90)
        self._poll_timer.timeout.connect(self._poll_playback_state)
        self.fallback_browser = QTextBrowser()
        self.fallback_browser.setOpenExternalLinks(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if self._load_web_engine():
            layout.addWidget(self.view, 1)
        else:
            layout.addWidget(self.fallback_browser, 1)
            self._update_fallback_html()

    def set_url(self, url: str) -> None:
        target = str(url or "").strip()
        if target == self._url:
            return
        self._url = target
        self._last_state_key = None
        self._poll_in_flight = False
        if self.view is not None:
            if target:
                self.view.load(QUrl(target))
                self._poll_timer.start()
            else:
                self._poll_timer.stop()
                self.view.setHtml("")
                self.playbackPositionChanged.emit(None)
            return
        self._poll_timer.stop()
        self.playbackPositionChanged.emit(None)
        self._update_fallback_html()

    def current_url(self) -> str:
        return self._url

    def shutdown(self) -> None:
        self._poll_timer.stop()
        if self.view is None:
            return
        try:
            self.view.stop()
        except RuntimeError:
            return

    def _load_web_engine(self) -> bool:
        try:
            from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
            from PyQt6.QtWebEngineWidgets import QWebEngineView
        except Exception:
            return False
        try:
            from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor
        except Exception:
            QWebEngineUrlRequestInterceptor = None

        try:
            storage_root = Path.home() / ".tab_analyzer" / "songsterr_web_sessions"
            storage_root.mkdir(parents=True, exist_ok=True)
            profile = QWebEngineProfile(f"tab-analyzer-songsterr-page-{os.getpid()}-{id(self)}", self)
            profile.setPersistentStoragePath(str(storage_root))
            profile.setCachePath(str(storage_root / "page_cache"))
            profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
            if QWebEngineUrlRequestInterceptor is not None:
                class SongsterrAdRequestInterceptor(QWebEngineUrlRequestInterceptor):
                    def interceptRequest(self, info) -> None:  # noqa: N802 - Qt API name.
                        try:
                            host = info.requestUrl().host()
                        except Exception:
                            return
                        if _is_songsterr_ad_request_host(host):
                            info.block(True)

                self._ad_request_interceptor = SongsterrAdRequestInterceptor(profile)
                profile.setUrlRequestInterceptor(self._ad_request_interceptor)
            try:
                from PyQt6.QtWebEngineCore import QWebEngineScript

                bridge_script = QWebEngineScript()
                bridge_script.setName("TabAnalyzerSongsterrBridge")
                bridge_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
                bridge_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
                bridge_script.setRunsOnSubFrames(False)
                bridge_script.setSourceCode(self._STAGE_BRIDGE_SCRIPT)
                profile.scripts().insert(bridge_script)

                ad_cleanup_script = QWebEngineScript()
                ad_cleanup_script.setName("TabAnalyzerSongsterrAdCleanup")
                ad_cleanup_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
                ad_cleanup_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
                ad_cleanup_script.setRunsOnSubFrames(True)
                ad_cleanup_script.setSourceCode(self._AD_CLEANUP_SCRIPT)
                profile.scripts().insert(ad_cleanup_script)
            except Exception:
                pass
            self._web_profile = profile
            self.view = QWebEngineView(self)
            self.view.setPage(QWebEnginePage(profile, self.view))
        except Exception:
            self._web_profile = None
            self._ad_request_interceptor = None
            self.view = None
            return False
        return True

    def _poll_playback_state(self) -> None:
        if self.view is None or not self._url or self._poll_in_flight:
            return
        try:
            page = self.view.page()
        except RuntimeError:
            self._poll_timer.stop()
            return
        self._poll_in_flight = True
        try:
            page.runJavaScript(self._PLAYBACK_STATE_SCRIPT, self._on_playback_state_polled)
        except RuntimeError:
            self._poll_in_flight = False
            self._poll_timer.stop()

    def _on_playback_state_polled(self, state: object) -> None:
        self._poll_in_flight = False
        if not isinstance(state, dict) or not state.get("available"):
            should_play = bool(state.get("shouldPlay")) if isinstance(state, dict) else False
            key = (-1, -1, should_play)
            if key != self._last_state_key:
                self._last_state_key = key
                self.playbackPositionChanged.emit(None)
            return

        try:
            measure_index = int(state.get("measureIndex", 0))
            ratio = float(state.get("ratio", 0.0))
        except (TypeError, ValueError):
            return
        should_play = bool(state.get("shouldPlay"))
        tick_bucket = int(max(0.0, min(0.999999, ratio)) * 3840)
        key = (measure_index, tick_bucket, should_play)
        if key == self._last_state_key:
            return
        self._last_state_key = key
        self.playbackPositionChanged.emit(
            {
                "measureIndex": measure_index,
                "ratio": ratio,
                "shouldPlay": should_play,
            }
        )

    def _update_fallback_html(self) -> None:
        if not self._url:
            self.fallback_browser.setHtml("")
            return
        safe_url = html.escape(self._url, quote=True)
        safe_text = html.escape(self._url)
        self.fallback_browser.setHtml(
            "<div style='font-family: Segoe UI, sans-serif; font-size: 12pt; padding: 20px;'>"
            "<p>PyQt6-WebEngine is unavailable, so the Songsterr page can be opened in an external browser.</p>"
            f"<p><a href='{safe_url}'>{safe_text}</a></p>"
            "</div>"
        )

