import time
import threading
import uuid
import io

import pydub
import requests

import my_log
import utils


OPEANAI_API_LOCK = threading.Lock()


def concatenate_wav_with_pydub_from_dict(wav_bytes_dict: dict[int, bytes]) -> bytes | None:
    """Concatenates a dictionary of wav byte strings (ordered by key) using pydub and returns the result as bytes.

    Args:
        wav_bytes_dict: A dictionary where keys are sequential integers representing the order,
                        and values are wav byte strings.

    Returns:
        The concatenated OGG data as bytes, or None if an error occurred.
    """
    combined = pydub.AudioSegment.empty()
    for i in sorted(wav_bytes_dict.keys()):  # Iterate through the dictionary in key order
        wav_bytes = wav_bytes_dict[i]
        try:
            audio = pydub.AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
            # Remove silence from the beginning and end of the audio segment
            audio = audio.strip_silence(silence_len=2000, silence_thresh=-40)  # Adjust parameters as needed
            combined += audio
        except Exception as e:

            return None

    try:
        ogg_stream = io.BytesIO()
        combined.export(ogg_stream, format="ogg", codec="libopus")  # Explicitly specify libopus
        return ogg_stream.getvalue()
    except Exception as e:

        return None


@utils.async_run_with_limit(4)
def openai_get_audio_bytes_(text: str, voice: str, prompt: str, chunks: dict, index: int):
    '''
    Работает в параллельном потоке, заполняет chunks данными
    изначально в данных записан None (снаружи проверяется не изменилось ли это)
    а в итоге байты или элемент вообще удаляется
    '''
    with OPEANAI_API_LOCK:
        if not prompt:
            prompt = 'Patient Teacher'
        if prompt == 'Connoisseur':
            prompt = '''Accent/Affect: slight French accent; sophisticated yet friendly, clearly understandable with a charming touch of French intonation.

    Tone: Warm and a little snooty. Speak with pride and knowledge for the art being presented.

    Pacing: Moderate, with deliberate pauses at key observations to allow listeners to appreciate details.

    Emotion: Calm, knowledgeable enthusiasm; show genuine reverence and fascination for the artwork.

    Pronunciation: Clearly articulate French words (e.g., "Mes amis," "incroyable") in French and artist names (e.g., "Leonardo da Vinci") with authentic French pronunciation.

    Personality Affect: Cultured, engaging, and refined, guiding visitors with a blend of artistic passion and welcoming charm.'''
        elif prompt == 'Calm':
            prompt = '''Voice Affect: Calm, composed, and reassuring; project quiet authority and confidence.

    Tone: Sincere, empathetic, and gently authoritative—express genuine apology while conveying competence.

    Pacing: Steady and moderate; unhurried enough to communicate care, yet efficient enough to demonstrate professionalism.

    Emotion: Genuine empathy and understanding; speak with warmth, especially during apologies ("I'm very sorry for any disruption...").

    Pronunciation: Clear and precise, emphasizing key reassurances ("smoothly," "quickly," "promptly") to reinforce confidence.

    Pauses: Brief pauses after offering assistance or requesting details, highlighting willingness to listen and support.'''
        elif prompt == 'Emo Teenager':
            prompt = '''Tone: Sarcastic, disinterested, and melancholic, with a hint of passive-aggressiveness.

    Emotion: Apathy mixed with reluctant engagement.

    Delivery: Monotone with occasional sighs, drawn-out words, and subtle disdain, evoking a classic emo teenager attitude.'''
        elif prompt == 'Serene':
            prompt = '''Voice Affect: Soft, gentle, soothing; embody tranquility.

    Tone: Calm, reassuring, peaceful; convey genuine warmth and serenity.

    Pacing: Slow, deliberate, and unhurried; pause gently after instructions to allow the listener time to relax and follow along.

    Emotion: Deeply soothing and comforting; express genuine kindness and care.

    Pronunciation: Smooth, soft articulation, slightly elongating vowels to create a sense of ease.

    Pauses: Use thoughtful pauses, especially between breathing instructions and visualization guidance, enhancing relaxation and mindfulness.'''
        elif prompt == 'Patient Teacher':
            prompt = '''Accent/Affect: Warm, refined, and gently instructive, reminiscent of a friendly art instructor. Very fast speech.

    Tone: Calm, encouraging, and articulate, clearly describing each step with patience.

    Pacing: Slow and deliberate, pausing often to allow the listener to follow instructions comfortably.

    Emotion: Cheerful, supportive, and pleasantly enthusiastic; convey genuine enjoyment and appreciation of art.

    Pronunciation: Clearly articulate artistic terminology (e.g., "brushstrokes," "landscape," "palette") with gentle emphasis.

    Personality Affect: Friendly and approachable with a hint of sophistication; speak confidently and reassuringly, guiding users through each painting step patiently and warmly.'''

        base_url = "https://www.openai.fm/api/generate"
        params = {
            "input": requests.utils.quote(text),
            "voice": voice,
            "generation": uuid.uuid4(),
        }
        if prompt:
            params["prompt"] = requests.utils.quote(prompt)

        request_url = f"{base_url}?{'&'.join([f'{k}={v}' for k, v in params.items()])}"

        headers = {
            "accept-encoding": "identity;q=1, *;q=0",
            "range": "bytes=0-",
            "referer": "https://www.openai.fm/",
            "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Opera";v="117"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 OPR/117.0.0.0",
        }

        response = requests.get(request_url, headers=headers, stream=True, timeout=30)

        if response.status_code == 200:
            wav_bytes = b"".join(chunk for chunk in response.iter_content(chunk_size=8192) if chunk)

            chunks[index] = wav_bytes
        else:
            # chunks[index] = b''
            # remove chunk
            chunks.pop(index, None)


def openai_get_audio_bytes(text: str, voice: str = "ash", prompt: str = '') -> bytes | None:
    """Generates audio from a URL with given text and voice, and returns it as OGG bytes using pydub.

    Args:
        text: The text to be converted to speech.
        voice: The voice to be used for speech synthesis. Defaults to "ash".
               Available voices: alloy, ash, ballad, coral, echo, fable, onyx, nova, sage, shimmer, verse.
        prompt: Optional prompt to guide the voice synthesis. Available prompts:
                Connoisseur, Calm, Emo Teenager, Serene, Patient Teacher or any other text.

    Returns:
        The audio data as bytes in OGG format, or None if an error occurred.
    """
    chunks = {}

    i = 0
    for chunk in utils.split_text(text, chunk_limit=999):
        i += 1
        chunks[i] = None
        openai_get_audio_bytes_(chunk, voice, prompt, chunks, i)

    # ждем оставшиеся 4 потока
    timeout = 90
    while timeout > 0:
        timeout -= 1
        time.sleep(1)
        if all(chunks.values()):
            break

    if not all(chunks.values()):
        my_log.log2('my_openai_voice.py: openai_get_audio_bytes: timeout')
        return b''

    return concatenate_wav_with_pydub_from_dict(chunks)


if __name__ == "__main__":

    text = """
КНИГА ПЕРВАЯ. СТАРТ


1


Все ясно. Лейкоз, лейкемия. В моем случае - год, может быть, два. Мир жестокий и голый. Кажется, я никогда его таким не видел. Думал, что все понял, все позвал и готов. Ничего не готов.
Подойду к окну. Мерзко и сыро на дворе. Декабрь без мороза и снега. Какие странные деревья: черные, тонкие ветви, ни единого сухого листика. Все снесло ветром, ни одного не осталось. Шарят по мокрому небу.
Люди бегут под фонарями в черных пальто.
Мне уже некуда спешить. Мне нужно теперь оценивать каждую минуту. Секунду. Нужно подержать ее в руках и с сожалением опустить. В корзине времени их все меньше и меньше. Обратно взять нельзя: они тают безвозвратно.
Не надо высокопарных фраз. Всю жизнь мы немножко рисуемся, хотя бы перед собой.
Вот этот анализ крови на столе, под лампой. Жалкий листочек бумаги, а на нем - приговор. Лейкоцитоз - сотни и сотни тысяч. И целый набор патологических форм кровяных телец.
Трудное положение было у Давида сегодня. Не позавидуешь. Хорошо, что я имею дело с собачками. Имел дело.
- У тебя с кровью не все в порядке, Ваня. Нужно лечиться.
Так мы и не назвали этого слова - лейкоз. Я прикинулся дурачком, а он, небось, подумал: "Слава богу, не понял".
Люба еще не знает. Тоже будут упреки: "Почему ты не пошел раньше? Сколько раз я тебя просила!.."
Каждый умирает в одиночку.
Фраза какая точная.
А хорошо, что у меня никого нет. Почти никого. Конечно, Любе будет очень плохо, но все-таки семья. Обязанности. Нужно скрывать, держать себя в руках. Если постоянно тормозить эмоции, то они и в самом деле исчезнут. Закон физиологии.
Вот теперь и не надо решать эту трудную проблему. Все откладывали: "Подождем еще лет пять, дети будут взрослые, поймут..." И я так боялся этого момента, когда все нужно будет открыть.
Теперь не нужно. Дотянем так. Больной - и осуждать не будут. Да и не за что будет осуждать. Последние месяцы было так редко... Наверное, это тоже болезнь. А я думал: почему? Любовь, что ли, прошла? Уж слишком много лет. Надежно.
Каждый - в одиночку.
Нет, ну почему все-таки я?! Разве мало других людей?! Я ведь еще должен столько сделать!
Только вошел во вкус, ухватился обеими руками... И... пожалуйста! Приехали! Черт знает что!.. Почему?!
Это, наверное, изотопные методики помогли. "Мирный атом". Все сам возился. Пусть бы занимались другие... Стоп! Не подличай. Каково бы было, если бы, например, у Юры? Нужно завтра же всем проверить кровь...
Вот так. "Ямщик... не гони... лошадей".
Почему мы так мало знаем? Рак, лейкоз - стоят проблемы перед нами, как я двадцать лет назад. Химия? Вирусы? Радиация?
Разгадка будет. Скоро. Уверен. Уже всерьез взялись за самое главное - механизм клеточного деления. ДНК. РНК.
Но уже не для меня.
Наверное, мне не стоит читать об этих лейкозах. Нужно положиться на Давида - хороший врач и приятель. Хватит того, что прочел в медицинской энциклопедии: "...от одного до двух лет". Чем больше знаешь, тем больше все болит. Вчера еще ничего, почти ничего не чувствовал, а теперь - пожалуйста! - уже в подреберье тяжесть, уже десны саднит, голова кружится.
Так, наверное, и буду все прислушиваться к своему телу. Потеряю свободу. Еще одну свободу. Всю жизнь оберегал ее, а теперь совсем потерял.
Пробуют пересадки костного мозга. Нужно разыскать статьи...
Может быть, удастся обмануть? Вдруг вылечусь? Опять войду в лабораторию без этих часов, отсчитывающих минуты? (Снова фраза.)
Не нужно обольщаться, друг. Привыкай к новому положению. К смерти. Дрожь по спине. Жестокое слово.
Так жалко себя! Хотя бы Люба пришла, приласкала. Погладила по голове. Просто погладила.
Позвонить? Может быть, запрет уже ни к чему?
Нет. Еще нельзя. Не нужно осложнений.
Странное ощущение. Как будто спокойно шел по дороге и вдруг - пропасть. Думал, вот впереди такой-то город, такая-то станция. Интересные дела, хорошая книга. И все исчезло. Осталось несколько метров пыльной дороги с редкими цветочками на обочине. И назад нельзя.
А что там было, позади? Э, брось, было много хорошего. Много.
Все меняется. Вчера еще спрашивал себя: "Повторить?" Нет, пусть идет вперед. Только вперед! А сегодня не прочь присесть и подождать. Посмотреть на цветочки.
Но уже нельзя.
Тело еще не верит. Как будто смотрю на сцену, где разыгрывается жалостливая пьеса. Знаю, что конец будет плохой, но можно сказать: "Это не со мной!"
Походим. Семь шагов от стола до шкафа. Еще семь - обратно. Туда - обратно. Туда - обратно. Некому даже оставить вещи. Как некому? А лаборатория? Будет у них своя библиотека, обстановка для кабинета или комнаты отдыха.
За стеклом перед книгами - сувениры. Их кому? Ослик из Стамбула. Статуя Свободы - из Нью-Йорка. Волчица кормит Ромула и Рема. Маленькая химера с Нотр-Дам. Воспоминания: конгрессы, доклады, аплодисменты, шум приемов. Все уйдет со мной.
Бешено размножаются эти клетки там, в костном мозге. Так и вижу, как они делятся, одна за другой. Одна за другой. Выпрыгивают, юные и голые, в кровеносное русло. Наводняют меня всего.
Хочется закричать: "Спасите!"
Вот когда станет трудно одному.
Позвать Леньку? Он еще не знает. Расскажу. Поплачусь.
И что? Что он скажет, кроме банальных слов утешения? Которые будут ему самому противны. Разве что напьется.
Не нужно. Ни с кем не нужно об этом говорить. Хватит Давида. Во всяком случае, пока есть свобода и воля.
Будут еще последние недели. Придется в больницу. Не хочу. Знаю, как там, - сам был и врачом и пациентом.
Протянуть как можно дольше дома. Еда, лекарства? Друзья и девушки из лаборатории будут приходить. (Люба, наверное, даже тогда не сможет.) Сколько хлопот им будет со мной!
Лучше уж в больницу. Можно прикрыть глаза и сказать: "Я устал". Облегчение на лицах: долг выполнен, можно уйти.
Опять окно. Черные, голые ветки. Ветер. Одиночество.
Казалось, давно привык, смирился. Даже доволен: никто не мешает. А теперь стало грустно.
Музыку? "Красные... помидоры... кушайте... без меня!"
Не может быть. Не может быть, что нет выхода. Вот так не верят люди в смерть. А врач виновато разводит руками: "Нельзя помочь".
Кофе? Рефлекс - 10 часов. Еще три часа работы. Работа? Она уже не нужна. Но кофе попьем.
Может быть, это сон? Дважды в жизни мне снился рак - было так же, если не хуже. Просыпался - "Ох, как хорошо!"
Хозяйство у меня какое налаженное! Кофе самый лучший. Мельница - ж-ж-ж! - и готово. Мощная. Венгерская кофеварка. Хорошая порция для одного.
Жду, пока закипит. Просто жду. Лучше бы выпить водки, да жаль, не привык. Теперь было бы кстати. Выпил и спи.
Какой приятный вкус! Кофе прибавляет оптимизма.
Мой друг, ведь ты считаешь себя ученым. Это так много - ученый. Человек, который может все разложить по полочкам. Оценить. Установить связи, создать системы. И, кроме того, он должен быть смелым. Владеть собой.
Остановись. Вытри слезы и слюни. Умирать еще не сейчас.
Попробуем взглянуть на вещи трезво. Перед лицом смерти. Но лучше без фраз. Взять бумагу и написать, как привык делать всегда.
Дано: я и болезнь. Найти оптимальное решение: что делать и как жить, чтобы получить максимум удовольствия и минимум неприятного.
Запишем: я - известный профессор-физиолог, 47 лет. Если закончу работу, то сделаю крупный вклад в медицинскую науку.
Мог бы уже сделать, уже сидел бы в академиках, если бы не разбрасывался. Помнишь? Сколько ошибок! Сколько лет даром пропало! Вот теперь бы их, эти годы!
Поздно сетовать. А вдруг что-нибудь придумают? Стоп.
Ну, а теперь "вклад" будет? Уверен?
Да, да, уверен. Все есть: идеи, методы, техника, коллектив. Эти мальчишки и девчонки. Милые, хорошие.
Вернемся к теме. Записано: "Получить максимум удовольствия.
Источники: а) Творчество. Воплощение". 
"""

    ogg_bytes = openai_get_audio_bytes(text=text)

    if ogg_bytes:
        print("Successfully retrieved OGG bytes.")
        # You can now work with the ogg_bytes (e.g., save to a file, play, etc.)
        # Example:
        with open("output.ogg", "wb") as f:
            f.write(ogg_bytes)
    else:
        print("Failed to retrieve OGG bytes.")
