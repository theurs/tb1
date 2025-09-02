# pip install cairosvg pytelegrambotapi python-chess stockfish
# sudo apt install stockfish

import telebot
from telebot import types
import chess
import chess.svg
from stockfish import Stockfish
import cairosvg
from typing import Dict, Any, Optional
import io
import os
import random
from sqlitedict import SqliteDict

# --- Globals & Config ---
# Assume cfg.py exists with a 'token' variable
try:
    from cfg import token
except ImportError:
    print("FATAL: cfg.py with 'token: str' not found.")
    exit(1)

# Path to your Stockfish binary.
# On Linux/macOS, often 'stockfish' or '/usr/local/bin/stockfish'. On Windows, 'stockfish.exe'.
STOCKFISH_PATH = "stockfish" 
bot = telebot.TeleBot(token)

# Create db directory if it doesn't exist
if not os.path.exists('db'):
    os.makedirs('db')

# Persistent storage for game states (key: str(user_id))
CHESS_SESSIONS = SqliteDict('db/chess_sessions.db', autocommit=True)

# Runtime cache for non-serializable objects (Board, Stockfish engine)
sessions: Dict[str, Dict[str, Any]] = {}


# --- Helper Functions ---
def get_game_over_reason(board: chess.Board) -> str:
    """Returns a human-readable string for the game's outcome."""
    if not board.is_game_over():
        return "Game is not over."

    outcome = board.outcome()
    termination = outcome.termination.name.replace("_", " ").title()

    if outcome.winner is True:
        winner = "White"
    elif outcome.winner is False:
        winner = "Black"
    else:
        return f"Game over: Draw by {termination}."

    return f"Game over: {winner} wins by {termination}."


# --- Session Management ---
def load_session_from_db(user_id: str) -> Optional[Dict[str, Any]]:
    """Loads a session from DB and initializes runtime objects."""
    if user_id in CHESS_SESSIONS:
        db_data = CHESS_SESSIONS[user_id]

        board = chess.Board(db_data['fen'])
        engine = Stockfish(path=STOCKFISH_PATH, parameters={"Threads": 2, "Hash": 256})

        runtime_session = {
            'board': board,
            'engine': engine,
            'message_id': db_data['message_id'],
            'player_color': db_data['player_color'],
            'chat_id': db_data['chat_id']
        }
        sessions[user_id] = runtime_session
        print(f"Session for user {user_id} loaded from DB into cache.")
        return runtime_session
    return None

def get_session(user_id: str) -> Optional[Dict[str, Any]]:
    """Gets a session from cache or loads it from DB."""
    if user_id in sessions:
        return sessions[user_id]
    return load_session_from_db(user_id)

def save_session(user_id: str) -> None:
    """Saves serializable parts of a session to the database."""
    if user_id in sessions:
        session = sessions[user_id]
        db_data = {
            'fen': session['board'].fen(),
            'message_id': session['message_id'],
            'player_color': session['player_color'],
            'chat_id': session['chat_id']
        }
        CHESS_SESSIONS[user_id] = db_data

def delete_session(user_id: str) -> None:
    """Deletes a session from cache and database."""
    if user_id in sessions:
        try:
            sessions[user_id]['engine'].send_quit_command()
        except Exception as e:
            print(f"Error quitting engine on session delete for {user_id}: {e}")
        del sessions[user_id]

    if user_id in CHESS_SESSIONS:
        del CHESS_SESSIONS[user_id]
    print(f"Session for user {user_id} deleted.")

def start_new_session(user_id: str, chat_id: int) -> Dict[str, Any]:
    """Creates a new runtime session for a user."""
    if user_id in sessions:
        try:
            sessions[user_id]['engine'].send_quit_command()
        except Exception as e:
            print(f"Error quitting old engine for user {user_id}: {e}")

    sessions[user_id] = {
        'board': chess.Board(),
        'engine': Stockfish(path=STOCKFISH_PATH, parameters={"Threads": 2, "Hash": 256}),
        'message_id': None,
        'chat_id': chat_id
    }
    print(f"New runtime session started for user_id: {user_id} in chat: {chat_id}")
    return sessions[user_id]


# --- UI & Board Rendering ---
def generate_move_keyboard(board: chess.Board, from_square: Optional[str] = None) -> types.InlineKeyboardMarkup:
    """Generates the keyboard for piece selection or move destination."""
    keyboard = types.InlineKeyboardMarkup(row_width=8)

    if from_square:
        # Step 2: Show possible destination squares for the selected piece
        buttons = []
        for move in board.legal_moves:
            if move.uci().startswith(from_square):
                to_square = move.uci()[2:]
                buttons.append(types.InlineKeyboardButton(text=to_square, callback_data=move.uci()))
        keyboard.add(*buttons)
        keyboard.row(types.InlineKeyboardButton(text="« Back", callback_data="back"))
    else:
        # Step 1: Show all pieces that can move
        if not board.is_game_over():
            movable_pieces = sorted(list(set([move.uci()[:2] for move in board.legal_moves])))
            buttons = [types.InlineKeyboardButton(text=square, callback_data=square) for square in movable_pieces]
            keyboard.add(*buttons)

    return keyboard

def update_board(user_id: str, text: str, last_move: Optional[chess.Move] = None) -> None:
    """Renders and updates the board, flipping it if the player is Black."""
    session = get_session(user_id)
    if not session or not session.get("message_id"):
        return

    board = session["board"]
    chat_id = session["chat_id"]
    message_id = session["message_id"]

    is_flipped = session.get("player_color") == chess.BLACK

    board_svg = chess.svg.board(
        board=board, lastmove=last_move, flipped=is_flipped
    ).encode("utf-8")

    png_bytes = io.BytesIO()
    cairosvg.svg2png(bytestring=board_svg, write_to=png_bytes)
    png_bytes.seek(0)

    keyboard = generate_move_keyboard(board)

    bot.edit_message_media(
        media=types.InputMediaPhoto(png_bytes),
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=keyboard,
    )
    bot.edit_message_caption(
        caption=text,
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=keyboard,
    )


# --- Telegram Handlers ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message: types.Message) -> None:
    """Handles start and help commands."""
    help_text = (
        "**Telegram Chess Bot**\n\n"
        "Play chess against the Stockfish engine.\n\n"
        "**Commands:**\n"
        "/newgame - Start a new game and choose your color.\n"
        "/undo - Undo your last move and the engine's response.\n"
        "/resign - Resign the current game.\n"
        "/help - Show this message."
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['newgame'])
def new_game(message: types.Message) -> None:
    """Offers the user to choose their side."""
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("⚪ White", callback_data="choose_color_white"),
        types.InlineKeyboardButton("⚫ Black", callback_data="choose_color_black"),
    )
    keyboard.row(
        types.InlineKeyboardButton("❓ Random", callback_data="choose_color_random")
    )
    bot.send_message(message.chat.id, "Choose your side:", reply_markup=keyboard)

@bot.message_handler(commands=['undo'])
def undo_move(message: types.Message) -> None:
    """Undoes the last pair of moves."""
    user_id = str(message.from_user.id)
    session = get_session(user_id)

    if not session:
        bot.reply_to(message, "No active game found.")
        return

    board = session['board']
    if len(board.move_stack) < 2:
        bot.reply_to(message, "Nothing to undo.")
        return

    board.pop()
    board.pop()

    save_session(user_id)
    update_board(user_id, "Last move undone. Your turn.")
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass # Ignore if message can't be deleted

@bot.message_handler(commands=['resign'])
def resign_game(message: types.Message) -> None:
    """Resigns the current game."""
    user_id = str(message.from_user.id)
    session = get_session(user_id)

    if not session:
        bot.reply_to(message, "No active game found.")
        return

    chat_id = session['chat_id']
    message_id = session['message_id']
    player_color_str = "White" if session['player_color'] == chess.WHITE else "Black"

    bot.edit_message_caption(
        caption=f"Game over. {player_color_str} resigned.",
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=None
    )
    delete_session(user_id)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call: types.CallbackQuery) -> None:
    """Handles all button presses for game interaction."""
    user_id = str(call.from_user.id)
    chat_id = call.message.chat.id
    data = call.data

    # --- Handler for Color Selection ---
    if data.startswith("choose_color_"):
        session = start_new_session(user_id, chat_id)
        board = session["board"]
        engine = session["engine"]

        color_choice = data.split("_")[-1]
        player_color = (
            random.choice([chess.WHITE, chess.BLACK]) if color_choice == "random" 
            else (chess.WHITE if color_choice == "white" else chess.BLACK)
        )
        session["player_color"] = player_color

        engine_move = None
        status_text = f"Game started. You play as {'White' if player_color == chess.WHITE else 'Black'}."

        # If player is Black, engine makes the first move
        if player_color == chess.BLACK:
            engine.set_fen_position(board.fen())
            best_move_uci = engine.get_best_move()
            engine_move = chess.Move.from_uci(best_move_uci)
            board.push(engine_move)
            status_text += f"\nEngine plays {best_move_uci}."

        bot.delete_message(chat_id, call.message.message_id)

        is_flipped = player_color == chess.BLACK
        board_svg = chess.svg.board(board=board, lastmove=engine_move, flipped=is_flipped).encode("utf-8")
        png_bytes = io.BytesIO()
        cairosvg.svg2png(bytestring=board_svg, write_to=png_bytes)
        png_bytes.seek(0)

        keyboard = generate_move_keyboard(board)
        sent_message = bot.send_photo(
            chat_id=chat_id, 
            photo=png_bytes, 
            caption=status_text, 
            reply_markup=keyboard
        )
        session["message_id"] = sent_message.message_id
        save_session(user_id)
        bot.answer_callback_query(call.id)
        return

    # --- Handler for In-Game Moves ---
    session = get_session(user_id)
    if not session:
        bot.answer_callback_query(call.id, text="Game session expired. Start /newgame.")
        return

    if session.get('thinking', False):
        bot.answer_callback_query(call.id, text="⏳ Engine is thinking, please wait...")
        return

    board = session["board"]

    # Go back to piece selection
    if data == "back":
        keyboard = generate_move_keyboard(board)
        bot.edit_message_caption("Choose a piece to move.", chat_id, session['message_id'], reply_markup=keyboard)
        bot.answer_callback_query(call.id)
        return

    # A piece has been selected, show destination squares
    if len(data) == 2 and data in [move.uci()[:2] for move in board.legal_moves]:
        keyboard = generate_move_keyboard(board, from_square=data)
        bot.edit_message_reply_markup(chat_id, session['message_id'], reply_markup=keyboard)
        bot.answer_callback_query(call.id, text=f"Selected {data}. Choose destination.")
        return

    # A full move has been made (e.g., e2e4)
    if len(data) == 4:
        try:
            move = chess.Move.from_uci(data)
            if move in board.legal_moves:
                board.push(move)
                save_session(user_id)

                if board.is_game_over():
                    reason = get_game_over_reason(board)
                    update_board(user_id, reason)
                    bot.edit_message_reply_markup(chat_id, session['message_id'], reply_markup=None)
                    delete_session(user_id)
                    return

                # --- SIMPLIFIED BLOCK ---
                # No more "thinking" status. Direct to engine move.
                engine = session['engine']
                engine.set_fen_position(board.fen())
                best_move_uci = engine.get_best_move()
                engine_move = chess.Move.from_uci(best_move_uci)
                board.push(engine_move)

                save_session(user_id)

                status_text = f"You: {data}. Engine: {best_move_uci}."

                if board.is_game_over():
                    reason = get_game_over_reason(board)
                    update_board(user_id, reason, last_move=engine_move)
                    bot.edit_message_reply_markup(chat_id, session['message_id'], reply_markup=None)
                    delete_session(user_id)
                else:
                    update_board(user_id, status_text, last_move=engine_move)

                bot.answer_callback_query(call.id)
            else:
                bot.answer_callback_query(call.id, text="Illegal move.", show_alert=True)
        except Exception as e:
            print(f"Error processing move for user {user_id}: {e}")
            bot.answer_callback_query(call.id, text="An error occurred.", show_alert=True)


if __name__ == '__main__':
    print("Bot is running...")
    bot.infinity_polling(skip_pending=True)