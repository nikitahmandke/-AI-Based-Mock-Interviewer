let mediaRecorder;
let audioChunks = [];

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  mediaRecorder = new MediaRecorder(stream);
  audioChunks = [];

  mediaRecorder.ondataavailable = (event) => {
    audioChunks.push(event.data);
  };

  mediaRecorder.onstop = async () => {
    const audioBlob = new Blob(audioChunks, { type: "audio/wav" });
    const formData = new FormData();
    formData.append("audio", audioBlob, "answer.wav");

    const response = await fetch("/process_audio", {
      method: "POST",
      body: formData
    });

    const result = await response.json();
    document.getElementById("aiResult").innerText =
      "🧠 AI Feedback: " + result.feedback;
  };

  mediaRecorder.start();
  document.getElementById("status").innerText = "🎙️ Recording...";
}

function stopRecording() {
  mediaRecorder.stop();
  document.getElementById("status").innerText = "✅ Recording stopped.";
}
