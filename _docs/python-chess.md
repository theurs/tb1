python-chess: a chess library for Python
Test status PyPI package Docs Chat on Gitter
Introduction

python-chess is a chess library for Python, with move generation, move validation, and support for common formats. This is the Scholar’s mate in python-chess:

import chess

board = chess.Board()

board.legal_moves  
<LegalMoveGenerator at ... (Nh3, Nf3, Nc3, Na3, h3, g3, f3, e3, d3, c3, ...)>

chess.Move.from_uci("a8a1") in board.legal_moves
False

board.push_san("e4")
Move.from_uci('e2e4')

board.push_san("e5")
Move.from_uci('e7e5')

board.push_san("Qh5")
Move.from_uci('d1h5')

board.push_san("Nc6")
Move.from_uci('b8c6')

board.push_san("Bc4")
Move.from_uci('f1c4')

board.push_san("Nf6")
Move.from_uci('g8f6')

board.push_san("Qxf7")
Move.from_uci('h5f7')

board.is_checkmate()
True

board
Board('r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4')

Installing

Requires Python 3.8+. Download and install the latest release:

pip install chess

Documentation

    Core

    PGN parsing and writing

    Polyglot opening book reading

    Gaviota endgame tablebase probing

    Syzygy endgame tablebase probing

    UCI/XBoard engine communication

    Variants

    Changelog

Features

    Includes mypy typings.

    IPython/Jupyter Notebook integration. SVG rendering docs.

board  

r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR

Chess variants: Standard, Chess960, Suicide, Giveaway, Atomic, King of the Hill, Racing Kings, Horde, Three-check, Crazyhouse. Variant docs.

Make and unmake moves.

Nf3 = chess.Move.from_uci("g1f3")

board.push(Nf3)  # Make the move

board.pop()  # Unmake the last move
Move.from_uci('g1f3')

Show a simple ASCII board.

board = chess.Board("r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4")

print(board)
r . b q k b . r
p p p p . Q p p
. . n . . n . .
. . . . p . . .
. . B . P . . .
. . . . . . . .
P P P P . P P P
R N B . K . N R

Detects checkmates, stalemates and draws by insufficient material.

board.is_stalemate()
False

board.is_insufficient_material()
False

board.outcome()
Outcome(termination=<Termination.CHECKMATE: 1>, winner=True)

Detects repetitions. Has a half-move clock.

board.can_claim_threefold_repetition()
False

board.halfmove_clock
0

board.can_claim_fifty_moves()
False

board.can_claim_draw()
False

With the new rules from July 2014, a game ends as a draw (even without a claim) once a fivefold repetition occurs or if there are 75 moves without a pawn push or capture. Other ways of ending a game take precedence.

board.is_fivefold_repetition()
False

board.is_seventyfive_moves()
False

Detects checks and attacks.

board.is_check()
True

board.is_attacked_by(chess.WHITE, chess.E8)
True

attackers = board.attackers(chess.WHITE, chess.F3)

attackers
SquareSet(0x0000_0000_0000_4040)

chess.G2 in attackers
True

print(attackers)
. . . . . . . .
. . . . . . . .
. . . . . . . .
. . . . . . . .
. . . . . . . .
. . . . . . . .
. . . . . . 1 .
. . . . . . 1 .

Parses and creates SAN representation of moves.

board = chess.Board()

board.san(chess.Move(chess.E2, chess.E4))
'e4'

board.parse_san('Nf3')
Move.from_uci('g1f3')

board.variation_san([chess.Move.from_uci(m) for m in ["e2e4", "e7e5", "g1f3"]])
'1. e4 e5 2. Nf3'

Parses and creates FENs, extended FENs and Shredder FENs.

board.fen()
'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

board.shredder_fen()
'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w HAha - 0 1'

board = chess.Board("8/8/8/2k5/4K3/8/8/8 w - - 4 45")

board.piece_at(chess.C5)
Piece.from_symbol('k')

Parses and creates EPDs.

board = chess.Board()

board.epd(bm=board.parse_uci("d2d4"))
'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - bm d4;'

ops = board.set_epd("1k1r4/pp1b1R2/3q2pp/4p3/2B5/4Q3/PPP2B2/2K5 b - - bm Qd1+; id \"BK.01\";")

ops == {'bm': [chess.Move.from_uci('d6d1')], 'id': 'BK.01'}
True

Detects absolute pins and their directions.

Reads Polyglot opening books. Docs.

import chess.polyglot

book = chess.polyglot.open_reader("data/polyglot/performance.bin")

board = chess.Board()

main_entry = book.find(board)

main_entry.move
Move.from_uci('e2e4')

main_entry.weight
1

book.close()

Reads and writes PGNs. Supports headers, comments, NAGs and a tree of variations. Docs.

import chess.pgn

with open("data/pgn/molinari-bordais-1979.pgn") as pgn:

    first_game = chess.pgn.read_game(pgn)

first_game.headers["White"]
'Molinari'

first_game.headers["Black"]
'Bordais'

first_game.mainline()  
<Mainline at ... (1. e4 c5 2. c4 Nc6 3. Ne2 Nf6 4. Nbc3 Nb4 5. g3 Nd3#)>

first_game.headers["Result"]
'0-1'

Probe Gaviota endgame tablebases (DTM, WDL). Docs.

Probe Syzygy endgame tablebases (DTZ, WDL). Docs.

import chess.syzygy

tablebase = chess.syzygy.open_tablebase("data/syzygy/regular")

# Black to move is losing in 53 half moves (distance to zero) in this

# KNBvK endgame.

board = chess.Board("8/2K5/4B3/3N4/8/8/4k3/8 b - - 0 1")

tablebase.probe_dtz(board)
-53

tablebase.close()

Communicate with UCI/XBoard engines. Based on asyncio. Docs.

import chess.engine

engine = chess.engine.SimpleEngine.popen_uci("stockfish")

board = chess.Board("1k1r4/pp1b1R2/3q2pp/4p3/2B5/4Q3/PPP2B2/2K5 b - - 0 1")

limit = chess.engine.Limit(time=2.0)

engine.play(board, limit)  
<PlayResult at ... (move=d6d1, ponder=c1d1, info={...}, draw_offered=False, resigned=False)>

    engine.quit()

Selected projects

If you like, share interesting things you are using python-chess for, for example:
https://github.com/niklasf/python-chess/blob/master/docs/images/syzygy.png?raw=true 	

https://syzygy-tables.info/

A website to probe Syzygy endgame tablebases
https://github.com/niklasf/python-chess/blob/master/docs/images/maia.png?raw=true 	

https://maiachess.com/

A human-like neural network chess engine
https://github.com/niklasf/python-chess/blob/master/docs/images/clente-chess.png?raw=true 	

clente/chess

Oppinionated wrapper to use python-chess from the R programming language
https://github.com/niklasf/python-chess/blob/master/docs/images/crazyara.png?raw=true 	

https://crazyara.org/

Deep learning for Crazyhouse
https://github.com/niklasf/python-chess/blob/master/docs/images/jcchess.png?raw=true 	

http://johncheetham.com

A GUI to play against UCI chess engines
https://github.com/niklasf/python-chess/blob/master/docs/images/pettingzoo.png?raw=true 	

https://pettingzoo.farama.org

A multi-agent reinforcement learning environment
https://github.com/niklasf/python-chess/blob/master/docs/images/cli-chess.png?raw=true 	

cli-chess

A highly customizable way to play chess in your terminal

    extensions to build engines (search and evaluation) – https://github.com/Mk-Chan/python-chess-engine-extensions

    a stand-alone chess computer based on DGT board – https://picochess.com/

    a bridge between Lichess API and chess engines – https://github.com/lichess-bot-devs/lichess-bot

    a command-line PGN annotator – https://github.com/rpdelaney/python-chess-annotator

    an HTTP microservice to render board images – https://github.com/niklasf/web-boardimage

    building a toy chess engine with alpha-beta pruning, piece-square tables, and move ordering – https://healeycodes.com/building-my-own-chess-engine/

    a JIT compiled chess engine – https://github.com/SamRagusa/Batch-First

    teaching Cognitive Science – https://jupyter.brynmawr.edu

    an Alexa skill to play blindfold chess – https://github.com/laynr/blindfold-chess

    a chessboard widget for PySide2 – https://github.com/H-a-y-k/hichesslib

    Django Rest Framework API for multiplayer chess – https://github.com/WorkShoft/capablanca-api

    a browser based PGN viewer written in PyScript – https://github.com/nmstoker/ChessMatchViewer

    an accessible chessboard that allows blind and visually impaired players to play chess against Stockfish – https://github.com/blindpandas/chessmart

    a web-based chess vision exercise – https://github.com/3d12/rookognition

Prior art

Thanks to the Stockfish authors and thanks to Sam Tannous for publishing his approach to avoid rotated bitboards with direct lookup (PDF) alongside his GPL2+ engine Shatranj. Some move generation ideas are taken from these sources.

Thanks to Ronald de Man for his Syzygy endgame tablebases. The probing code in python-chess is very directly ported from his C probing code.

Thanks to Kristian Glass for transferring the namespace chess on PyPI.
