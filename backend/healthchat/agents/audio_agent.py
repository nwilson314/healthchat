import io
import re
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from openai import OpenAI

LLM_SYSTEM_PROMPT = """
Engage in a conversation as a nurse with an elderly patient, ensuring a compassionate and 
understanding approach to their needs, providing support, and maintaining a positive relationship.

- Greet the patient warmly and establish a caring tone.
- Ask gentle, open-ended questions to understand the patient's concerns and preferences.
- Provide clear and supportive information or solutions based on the patient's needs or feedback.
- Use active listening skills to ensure the patient feels heard and respected.
- Summarize key points of the conversation to confirm understanding and reassure the patient.
- End the conversation with expressions of gratitude and offer further assistance.


# Output Format
- You are the nurse. Your response should ONLY be the nurse's part of the conversation.
- Do NOT write "Nurse:" or any other prefix before your response.
- Do NOT invent the patient's response. Respond directly to the user's input.
- Keep your responses concise and natural.

# Examples
## Example 1
- **User Input:** "I've been feeling a bit lonely lately."
- **Your Response:** "I'm sorry to hear you've been feeling lonely. Thank you for sharing that with me. Sometimes just talking about it can help. Is there anything on your mind you'd like to chat about?"

## Example 2
- **User Input:** "My back is really aching today."
- **Your Response:** "I understand that backaches can be very uncomfortable. Have you tried a warm compress? Sometimes that can provide a bit of relief. If it continues to bother you, it might be a good idea to mention it to your doctor."


# Notes
- Always maintain a professional yet compassionate demeanor.
- Ensure empathy and understanding are communicated through your tone and language.
- Be attentive to the patient's verbal and non-verbal cues, especially in face-to-face encounters."
"""

class AudioAgent:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.ai_client = OpenAI()
        # Queues for pipeline stages
        self.audio_input_queue = asyncio.Queue()
        self.transcript_queue = asyncio.Queue()
        self.llm_response_queue = asyncio.Queue()
        self.tts_audio_queue = asyncio.Queue()
        self.conversation_history = [{"role": "system", "content": LLM_SYSTEM_PROMPT}]

    async def run(self):
        try:
            # The main loop now orchestrates a 5-stage pipeline
            await asyncio.gather(
                self._receive_from_client(),    # 1. Receive audio
                self._process_stt(),            # 2. Transcribe
                self._process_llm(),            # 3. Get LLM response
                self._process_tts(),            # 4. Generate audio
                self._send_tts_audio()          # 5. Send audio
            )
        except Exception as e:
            print(f"An error occurred in the agent's main run loop: {e}")

    # Helper methods for OpenAI API calls
    def _openai_stt(self, audio_file: io.BytesIO) -> str | None:
        try:
            return self.ai_client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe", 
                file=audio_file, 
                response_format="text",
                language="EN"
            )
        except Exception as e:
            print(f"STT Error: {e}")
            return None

    def _openai_converse_stream(self):
        try:
            stream = self.ai_client.chat.completions.create(
                model="gpt-4o",
                messages=self.conversation_history,
                stream=True
            )
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except Exception as e:
            print(f"LLM Stream Error: {e}")

    def _generate_tts_audio(self, text: str):
        """Synchronous generator for TTS audio chunks."""
        try:
            with self.ai_client.audio.speech.with_streaming_response.create(
                model="gpt-4o-mini-tts", 
                voice="nova", 
                input=text
            ) as response:
                for chunk in response.iter_bytes(chunk_size=4096):
                    yield chunk
        except Exception as e:
            print(f"TTS Error: {e}")

    # Core async tasks
    async def _receive_from_client(self):
        try:
            while True:
                message = await self.websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("bytes"):
                    data = message.get("bytes")
                    await self.audio_input_queue.put(data)
                elif message.get("text") and message["text"] == "EndOfStream":
                    await self.audio_input_queue.put(None)
        except WebSocketDisconnect:
            print("Client disconnected.")
        finally:
            # On disconnect, signal all downstream tasks to exit gracefully
            await self.audio_input_queue.put(None)
            await self.transcript_queue.put(None)
            await self.llm_response_queue.put(None)
            await self.tts_audio_queue.put(None)

    async def _process_stt(self):
        while True:
            first_chunk = await self.audio_input_queue.get()
            if first_chunk is None: break

            audio_chunks = [first_chunk]
            while True:
                chunk = await self.audio_input_queue.get()
                if chunk is None:
                    break
                audio_chunks.append(chunk)

            full_audio_stream = b''.join(audio_chunks)
            if not full_audio_stream: continue

            audio_file = io.BytesIO(full_audio_stream)
            audio_file.name = "audio.webm"

            await self.websocket.send_json({"type": "status", "message": "Transcribing..."})
            transcript = self._openai_stt(audio_file)

            if transcript:
                await self.websocket.send_json({"type": "transcript", "data": transcript})
                await self.transcript_queue.put(transcript)
            else:
                await self.websocket.send_json({"type": "status", "message": "Transcription failed."})

    async def _process_llm(self):
        while True:
            transcript = await self.transcript_queue.get()
            if transcript is None: break

            self.conversation_history.append({"role": "user", "content": transcript})

            await self.websocket.send_json({"type": "status", "message": "Thinking..."})
            await self.websocket.send_json({"type": "llm_response_start"})

            full_response = []
            last_sentence = []
            end_punc = [".", "!", "?"]
            for chunk in self._openai_converse_stream():
                full_response.append(chunk)
                last_sentence.append(chunk)
                await self.websocket.send_json({"type": "llm_chunk", "data": chunk})

                if len(chunk) == 1 and chunk in end_punc:
                    await self.llm_response_queue.put("".join(last_sentence))
                    last_sentence = []
            
            if full_response:
                self.conversation_history.append({"role": "assistant", "content": "".join(full_response)})
            else:
                await self.websocket.send_json({"type": "status", "message": "AI failed to respond."})

    async def _process_tts(self):
        while True:
            full_response = await self.llm_response_queue.get()
            if full_response is None: break

            await self.websocket.send_json({"type": "status", "message": "Streaming audio..."})

            sentences = [full_response.strip()]
            for sentence in sentences:
                if not sentence: continue
                loop = asyncio.get_running_loop()
                audio_generator = await loop.run_in_executor(None, self._generate_tts_audio, sentence)
                sentence_chunks = []
                for chunk in audio_generator:
                    sentence_chunks.append(chunk)
                full_audio_stream = b''.join(sentence_chunks)

                audio_file = io.BytesIO(full_audio_stream)
                audio_file.name = "audio.webm"
                await self.tts_audio_queue.put(audio_file)
            
            await self.tts_audio_queue.put(b'--AUDIO_END--')

    async def _send_tts_audio(self):
        while True:
            chunk = await self.tts_audio_queue.get()
            if chunk is None: break
            
            if chunk == b'--AUDIO_END--':
                await self.websocket.send_json({"type": "audio_end"})
            else:
                await self.websocket.send_bytes(chunk)