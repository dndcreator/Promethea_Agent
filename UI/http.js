(function () {
    const DEFAULT_API_BASE = "http://127.0.0.1:8000";

    function resolveApiBase() {
        const fromConfig = window.__APP_CONFIG__ && window.__APP_CONFIG__.apiBaseUrl;
        const fromGlobal = window.__PROMETHEA_API_BASE__;
        const fromStorage = localStorage.getItem("api_base_url");
        const raw = String(fromConfig || fromGlobal || fromStorage || DEFAULT_API_BASE).trim();
        return raw.replace(/\/+$/, "");
    }

    function getAuthToken() {
        const sessionToken = sessionStorage.getItem("auth_token");
        if (sessionToken) return sessionToken;
        const legacyToken = localStorage.getItem("auth_token");
        if (legacyToken) {
            sessionStorage.setItem("auth_token", legacyToken);
            localStorage.removeItem("auth_token");
            return legacyToken;
        }
        return "";
    }

    function setAuthToken(token) {
        if (!token) return;
        sessionStorage.setItem("auth_token", String(token));
        localStorage.removeItem("auth_token");
    }

    function clearAuthToken() {
        sessionStorage.removeItem("auth_token");
        localStorage.removeItem("auth_token");
    }

    function buildAuthHeaders(headers) {
        const out = { ...(headers || {}) };
        const token = getAuthToken();
        if (token && !out.Authorization) {
            out.Authorization = `Bearer ${token}`;
        }
        return out;
    }

    async function authFetch(url, options) {
        const next = { ...(options || {}) };
        next.headers = buildAuthHeaders(next.headers);
        if (!Object.prototype.hasOwnProperty.call(next, "credentials")) {
            next.credentials = "include";
        }
        return fetch(url, next);
    }

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function renderMultilineText(container, value) {
        if (!container) return;
        const text = String(value || "");
        container.textContent = text;
        container.style.whiteSpace = "pre-wrap";
    }

    window.AppHttp = {
        resolveApiBase,
        getAuthToken,
        setAuthToken,
        clearAuthToken,
        buildAuthHeaders,
        authFetch,
        escapeHtml,
        renderMultilineText,
    };
})();
