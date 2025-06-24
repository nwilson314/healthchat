<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { PUBLIC_API_URL } from '$env/static/public';

  type Message = { role: 'user' | 'assistant'; content: string };

  // UI State
  let status = 'Initializing...';
  let conversation: Message[] = [];
  let isRecording = false;

  // Core components
  let socket: WebSocket | null = null;
  let mediaRecorder: MediaRecorder | null = null;
  let localStream: MediaStream | null = null;

  // New variables for streaming audio playback
  let audioPlayer: HTMLAudioElement;
  let audioQueue: Blob[] = [];
  let isPlayingAudio = false;

  onMount(() => {
    status = 'Connecting to server...';
    socket = new WebSocket(`ws://${PUBLIC_API_URL}/ws/chat`);

    socket.onopen = () => {
      status = 'Ready';
    };

    socket.onmessage = (event) => {
      if (event.data instanceof Blob) {
        audioQueue.push(event.data);
        playNextInQueue(); // Trigger the playback loop
      } else {
        try {
          const message = JSON.parse(event.data);
          switch (message.type) {
            case 'status':
              status = message.message;
              break;
            case 'transcript':
              conversation = [...conversation, { role: 'user', content: message.data }];
              break;
            case 'llm_response_start':
              // Add a placeholder for the assistant's message
              conversation = [...conversation, { role: 'assistant', content: '' }];
              break;
            case 'llm_chunk':
              // Find the last message (which should be the assistant's) and append the chunk
              if (conversation.length > 0) {
                const lastMessage = conversation[conversation.length - 1];
                if (lastMessage.role === 'assistant') {
                  lastMessage.content += message.data;
                  conversation = [...conversation]; // This is key to trigger Svelte's reactivity
                }
              }
              break;
            case 'audio_end':
              status = 'Ready';
              break;
          }
        } catch (e) {
          console.error('Failed to parse JSON message:', event.data, e);
        }
      }
    };

    socket.onerror = (error) => {
      status = 'Connection Error';
      console.error('WebSocket error:', error);
      cleanupAudio();
    };

    socket.onclose = () => {
      status = 'Disconnected';
      isRecording = false;
      cleanupAudio();
    };
  });

  onDestroy(() => {
    cleanupAudio();
    if (socket) {
      socket.close();
    }
  });

  function cleanupAudio() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop();
    }
    if (localStream) {
      localStream.getTracks().forEach(track => track.stop());
    }
    localStream = null;
    mediaRecorder = null;
  }

  async function toggleRecording() {
    if (isRecording) {
      isRecording = false;
      status = 'Processing...';
      cleanupAudio();
    } else {
      if (status !== 'Ready') return;
      isRecording = true;
      status = 'Listening...';
      // We don't clear the conversation history anymore
      audioQueue = [];

      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        localStream = stream;
        const options = { mimeType: 'audio/webm;codecs=opus' };
        mediaRecorder = new MediaRecorder(stream, options);

        mediaRecorder.ondataavailable = (event) => {
          if (event.data.size > 0 && socket?.readyState === WebSocket.OPEN) {
            socket.send(event.data);
          }
        };

        mediaRecorder.onstop = () => {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send('EndOfStream');
          }
        };

        mediaRecorder.start(250);
      } catch (error) {
        console.error('Error accessing microphone:', error);
        status = 'Mic Error';
        isRecording = false;
      }
    }
  }

  // A self-contained function to play one audio blob and return a promise
  function playAudio(blob: Blob): Promise<void> {
    return new Promise((resolve, reject) => {
      // Re-create the blob with the correct MIME type to prevent browser errors
      const audioBlob = new Blob([blob], { type: 'audio/mpeg' });
      const url = URL.createObjectURL(audioBlob);
      audioPlayer.src = url;
      audioPlayer.onended = () => {
        URL.revokeObjectURL(url); // Clean up memory
        resolve();
      };
      audioPlayer.onerror = (e) => {
        URL.revokeObjectURL(url); // Clean up memory
        reject(e);
      };
      audioPlayer.play();
    });
  }

  // A simple, robust loop to play audio from the queue sequentially
  async function playNextInQueue() {
    if (isPlayingAudio) return; // A playback loop is already running.
    isPlayingAudio = true;

    while (audioQueue.length > 0) {
      const blob = audioQueue.shift();
      if (blob) {
        try {
          await playAudio(blob);
        } catch (e) {
          console.error("Audio playback failed, clearing queue.", e);
          audioQueue = []; // Clear the queue on error
          break; // Exit the loop on error
        }
      }
    }

    isPlayingAudio = false;

    // One final check to prevent a race condition.
    // If a chunk arrived while the loop was finishing, play it now.
    if (audioQueue.length > 0) {
      playNextInQueue();
    }
  }
</script>
  
<audio bind:this={audioPlayer} style="display: none;"></audio>
  
<div class="flex flex-col items-center justify-center min-h-screen bg-gray-900 text-white font-sans">
  <div class="w-full max-w-4xl p-8 space-y-6">
    
    <!-- Header -->
    <div class="text-center">
      <h1 class="text-4xl font-bold text-cyan-400">HealthCheck AI</h1>
      <p class="text-lg text-gray-400">Your real-time conversational health assistant</p>
    </div>

    <!-- Status Indicator -->
    <div class="text-center p-2 bg-gray-800 rounded-lg">
      <p class="text-sm font-medium text-gray-300">STATUS: <span class="font-bold text-cyan-400">{status}</span></p>
    </div>

    <!-- Conversation History -->
    <div class="bg-gray-800 p-4 rounded-lg shadow-md h-[60vh] overflow-y-auto flex flex-col space-y-4">
      {#if conversation.length === 0}
        <div class="flex-grow flex items-center justify-center">
          <p class="text-gray-500">Conversation will appear here...</p>
        </div>
      {/if}
      {#each conversation as message, i (i)}
        <div class="flex" class:justify-end={message.role === 'user'} class:justify-start={message.role === 'assistant'}>
          <div 
            class="max-w-md p-3 rounded-lg"
            class:bg-cyan-600={message.role === 'user'}
            class:text-white={message.role === 'user'}
            class:bg-gray-700={message.role === 'assistant'}
            class:text-gray-200={message.role === 'assistant'}
          >
            <p class="whitespace-pre-wrap">{message.content || '...'}</p>
          </div>
        </div>
      {/each}
    </div>

    <!-- Action Button -->
    <div class="flex justify-center pt-4">
      <button 
        on:click={toggleRecording}
        disabled={status !== 'Ready' && !isRecording}
        class="select-none px-8 py-5 rounded-full text-white font-bold transition-all duration-200 ease-in-out focus:outline-none ring-4 ring-cyan-500/50 disabled:bg-gray-600 disabled:ring-gray-600"
        class:bg-red-600={isRecording}
        class:hover:bg-red-700={isRecording}
        class:scale-110={isRecording}
        class:bg-cyan-500={!isRecording}
        class:hover:bg-cyan-600={!isRecording && status === 'Ready'}
      >
        {isRecording ? 'Stop Recording' : 'Press to Talk'}
      </button>
    </div>

  </div>
</div>