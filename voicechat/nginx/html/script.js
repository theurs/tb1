// script.js
import { updateStatus, getUserIdFromURL, resetSilenceTimer, SILENCE_THRESHOLD } from './utils.js';

let mediaRecorder;
let audioChunks = [];
let silenceTimer;
let userId;
let isFirst = true; // Flag to indicate if it's the first recording

async function startRecording() {
    if (isFirst) {
        updateStatus("Слушаю");
        isFirst = false;
    } else {
        updateStatus("Слушаю");
    }
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);

        mediaRecorder.ondataavailable = (event) => {
            console.log("Data available:", event.data);
            audioChunks.push(event.data);
            resetSilenceTimer();
        };

        mediaRecorder.onstop = async () => {
            //updateStatus("Recording stopped.");
            await sendAudio();
            audioChunks = [];
        };

        mediaRecorder.start();
        //updateStatus("Recording started.");
        detectSilence();

    } catch (error) {
        updateStatus(`Ошибка микрофона: ${error.message}`);
    }
}

async function sendAudio() {
    updateStatus("Отправляю...");
    if (audioChunks.length === 0) {
        updateStatus("Нет данных для отправки.");
        startRecording();
        return;
    }

    const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
    const formData = new FormData();
    formData.append('audio', audioBlob);
    formData.append('user_id', userId);

    try {
        const response = await fetch('https://voicechat.dns.army/voice', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Ошибка сервера: ${response.status} ${errorText}`);
        }

        const responseBlob = await response.blob();
        updateStatus("Получаю...");
        await playAudio(await responseBlob.arrayBuffer(), () => {
            updateStatus("Отвечаю(голосом)");
            startRecording();
        });
    } catch (error) {
        if (error.name === 'TypeError' || error.message.includes('NetworkError')) {
            updateStatus("Ошибка сети: Проверьте подключение к интернету.");
        } else if (error.message.startsWith('Ошибка сервера')) {
            updateStatus(error.message);
        }
        else {
            updateStatus(`Неизвестная ошибка: ${error.message}`);
        }
        startRecording()
    }
}

// Function to detect silence
function detectSilence() {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = audioContext.createAnalyser();
    const source = audioContext.createMediaStreamSource(mediaRecorder.stream);
    source.connect(analyser);
    analyser.fftSize = 2048;

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    const checkSilence = () => {
        analyser.getByteTimeDomainData(dataArray);
        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
            sum += Math.abs(dataArray[i] - 128);
        }
        const average = sum / bufferLength;

        // ИЗМЕНЕНИЕ: Увеличиваем порог тишины, например, до 10
        if (average < 10) {
            if (!silenceTimer) {

                silenceTimer = setTimeout(() => {
                    if (mediaRecorder.state === 'recording') {
                        mediaRecorder.stop();
                    }
                }, SILENCE_THRESHOLD);
            }
        } else {
            clearTimeout(silenceTimer);
            silenceTimer = null;
        }

        requestAnimationFrame(checkSilence);
    };

    checkSilence();
}

async function playAudio(arrayBuffer, onAudioEnded) {
    //updateStatus("Playing audio...");
    try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const buffer = await audioContext.decodeAudioData(arrayBuffer);
        const source = audioContext.createBufferSource();
        source.buffer = buffer;
        source.connect(audioContext.destination);
        source.onended = onAudioEnded;
        source.start();
    } catch (error) {
        updateStatus(`Ошибка воспроизведения: ${error.message}`);
    }
}

window.onload = () => {
    userId = getUserIdFromURL();
    if (userId) {
        updateStatus("Готов");
        startRecording(); // Start recording immediately when the page loads
    } else {
        updateStatus("Ошибка: user_id не найден", true);
    }
};
