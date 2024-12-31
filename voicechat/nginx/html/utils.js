// utils.js
export function updateStatus(message) {
    const statusText = document.getElementById('statusText');
    const currentTime = new Date().toLocaleTimeString();
    const logMessage = `${currentTime} - ${message}\n`;
    statusText.textContent = logMessage + statusText.textContent;
    console.log(message);
}

export function getUserIdFromURL() {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('user_id');
}

export function resetSilenceTimer(silenceTimer) {
    clearTimeout(silenceTimer);
    silenceTimer = null;
}

export const SILENCE_THRESHOLD = 1000; // Silence threshold in milliseconds
