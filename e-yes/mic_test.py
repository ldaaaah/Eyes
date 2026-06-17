import speech_recognition as sr

recognizer = sr.Recognizer()
microphone = sr.Microphone()

print("🎙️ 마이크 세팅 완료! 아무 말이나 해보세요...")

with microphone as source:
    recognizer.adjust_for_ambient_noise(source)
    print("🗣️ 듣고 있습니다... (말씀해주세요!)")
    audio_data = recognizer.listen(source)

print("⏳ 구글 서버에서 번역 중...")

try:
    text = recognizer.recognize_google(audio_data, language='ko-KR')
    print(f"\n💡 [인식 성공!]: {text}")
except Exception as e:
    print(f"❌ [에러] {e}")
