"""
Web routes for the System Shock 2 themed UI.
Provides REST API endpoints for all UI operations.
"""

import copy
import html
import json
import time
import asyncio
from pathlib import Path
from threading import Thread

import yaml
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse

import modules.shared as shared
from modules.logging_colors import logger
from modules.utils import (
    get_available_models,
    get_available_characters,
    get_available_users,
    get_available_presets,
    get_available_prompts,
    get_available_extensions,
    get_available_loras,
    get_available_instruction_templates,
    get_available_grammars,
    get_available_chat_styles,
    get_available_image_models,
    get_available_mmproj,
)

router = APIRouter(prefix="/api")


# ─────────────────────────── Helpers ───────────────────────────

def _build_state(params=None):
    """Build a generation state dict from current settings + overrides."""
    state = copy.deepcopy(shared.settings)
    state.update(shared.persistent_interface_state)
    if params:
        state.update(params)

    # Ensure history exists
    if 'history' not in state or state['history'] is None:
        state['history'] = {'internal': [], 'visible': [], 'metadata': {}}

    # Ensure character_menu key exists (used by chat.py functions)
    if 'character_menu' not in state:
        state['character_menu'] = state.get('character', 'Assistant')

    # Ensure user_menu key exists
    if 'user_menu' not in state:
        state['user_menu'] = state.get('user', 'Default')

    # Ensure search_chat key exists
    if 'search_chat' not in state:
        state['search_chat'] = ''

    # Ensure branch_index key exists
    if 'branch_index' not in state:
        state['branch_index'] = -1

    return state


def _get_model_info():
    """Return current model info."""
    return {
        'model_name': shared.model_name,
        'is_loaded': shared.model is not None,
        'is_seq2seq': shared.is_seq2seq,
        'is_multimodal': shared.is_multimodal,
        'lora_names': shared.lora_names,
        'loader': getattr(shared.args, 'loader', None),
        'truncation_length': shared.settings.get('truncation_length', 8192),
    }


# ─────────────────────────── System ───────────────────────────

@router.get("/status")
async def get_status():
    """System status with model info."""
    return JSONResponse({
        'model': _get_model_info(),
        'settings': {k: v for k, v in shared.settings.items()
                     if not k.endswith('_str') and k != 'chat-instruct_command'},
    })


# ─────────────────────────── Models ───────────────────────────

@router.get("/models/list")
async def list_models():
    return JSONResponse({
        'models': get_available_models(),
        'current': shared.model_name,
        'loader': getattr(shared.args, 'loader', None),
    })


@router.post("/models/load")
async def load_model_endpoint(request: Request):
    data = await request.json()
    model_name = data.get('model_name')
    loader = data.get('loader')

    if not model_name:
        return JSONResponse({'error': 'model_name required'}, status_code=400)

    try:
        from modules.models import load_model, unload_model
        from modules.models_settings import get_model_metadata, update_model_parameters

        unload_model()

        model_settings = get_model_metadata(model_name)
        update_model_parameters(model_settings, initial=True)

        if loader:
            shared.args.loader = shared.fix_loader_name(loader) or loader

        shared.model, shared.tokenizer = load_model(model_name)
        if shared.model is not None:
            return JSONResponse({'status': 'ok', 'model': _get_model_info()})
        else:
            return JSONResponse({'error': 'Failed to load model'}, status_code=500)
    except Exception as e:
        logger.exception("Error loading model")
        return JSONResponse({'error': str(e)}, status_code=500)


@router.post("/models/unload")
async def unload_model_endpoint():
    from modules.models import unload_model
    unload_model()
    return JSONResponse({'status': 'ok', 'model': _get_model_info()})


# ─────────────────────────── Characters ───────────────────────

@router.get("/characters/list")
async def list_characters():
    return JSONResponse({
        'characters': get_available_characters(),
        'current': shared.settings.get('character', 'Assistant'),
    })


@router.get("/characters/{name}")
async def get_character(name: str):
    try:
        from modules.chat import load_character
        name1, name2, picture, greeting, context = load_character(
            name,
            shared.settings.get('name1', 'You'),
            shared.settings.get('name2', 'AI')
        )
        return JSONResponse({
            'name1': name1,
            'name2': name2,
            'greeting': greeting,
            'context': context,
            'has_picture': picture is not None,
            'picture_path': picture,
        })
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=404)


@router.post("/characters/save")
async def save_character(request: Request):
    data = await request.json()
    name = data.get('name', '').strip()
    if not name:
        return JSONResponse({'error': 'name required'}, status_code=400)

    from modules.utils import sanitize_filename, save_file
    name = sanitize_filename(name)
    char_data = {
        'name': data.get('name2', name),
        'context': data.get('context', ''),
        'greeting': data.get('greeting', ''),
    }
    if data.get('name1'):
        char_data['your_name'] = data['name1']

    filepath = str(shared.user_data_dir / 'characters' / f'{name}.yaml')
    save_file(filepath, yaml.dump(char_data, allow_unicode=True))
    return JSONResponse({'status': 'ok'})


@router.post("/characters/delete")
async def delete_character(request: Request):
    data = await request.json()
    name = data.get('name', '').strip()
    if not name:
        return JSONResponse({'error': 'name required'}, status_code=400)

    from modules.utils import sanitize_filename, delete_file
    name = sanitize_filename(name)
    for ext in ['yaml', 'yml', 'json']:
        p = shared.user_data_dir / 'characters' / f'{name}.{ext}'
        if p.exists():
            delete_file(str(p))
            break

    return JSONResponse({'status': 'ok'})


# ─────────────────────────── Chat ─────────────────────────────

@router.get("/chat/histories")
async def list_chat_histories():
    from modules.chat import find_all_histories_with_first_prompts
    state = _build_state()
    histories = find_all_histories_with_first_prompts(state)
    return JSONResponse({'histories': histories})


@router.get("/chat/history/{unique_id}")
async def get_chat_history(unique_id: str):
    from modules.chat import load_history
    state = _build_state()
    history = load_history(unique_id, state.get('character_menu', state.get('character', 'Assistant')), state.get('mode', 'instruct'))
    return JSONResponse({'history': history})


@router.post("/chat/new")
async def new_chat():
    from modules.chat import start_new_chat
    from datetime import datetime
    state = _build_state()
    history = start_new_chat(state)
    # start_new_chat saves with a timestamp-based unique_id
    unique_id = datetime.now().strftime('%Y%m%d-%H-%M-%S')
    return JSONResponse({'history': history, 'unique_id': unique_id})


@router.post("/chat/delete")
async def delete_chat(request: Request):
    data = await request.json()
    unique_id = data.get('unique_id')
    if not unique_id:
        return JSONResponse({'error': 'unique_id required'}, status_code=400)

    from modules.chat import delete_history
    state = _build_state()
    delete_history(unique_id, state.get('character_menu', state.get('character', 'Assistant')), state.get('mode', 'instruct'))
    return JSONResponse({'status': 'ok'})


@router.post("/chat/rename")
async def rename_chat(request: Request):
    data = await request.json()
    old_id = data.get('old_id')
    new_id = data.get('new_id')
    if not old_id or not new_id:
        return JSONResponse({'error': 'old_id and new_id required'}, status_code=400)

    from modules.chat import rename_history
    state = _build_state()
    rename_history(old_id, new_id, state.get('character_menu', state.get('character', 'Assistant')), state.get('mode', 'instruct'))
    return JSONResponse({'status': 'ok'})


@router.post("/chat/stop")
async def stop_generation():
    shared.stop_everything = True
    return JSONResponse({'status': 'ok'})


# ─────────────────────────── Settings ─────────────────────────

@router.get("/settings")
async def get_settings():
    return JSONResponse(shared.settings)


@router.post("/settings")
async def update_settings(request: Request):
    data = await request.json()
    shared.settings.update(data)
    shared.persistent_interface_state.update(data)

    # Persist to disk
    try:
        settings_path = shared.user_data_dir / 'settings.yaml'
        output = copy.deepcopy(shared.settings)
        # Remove template strings that are too large
        for key in list(output.keys()):
            if key in shared.default_settings and output[key] == shared.default_settings[key]:
                output.pop(key)
        with open(settings_path, 'w', encoding='utf-8') as f:
            f.write(yaml.dump(output, sort_keys=False, width=float("inf"), allow_unicode=True))
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")

    return JSONResponse({'status': 'ok'})


# ─────────────────────────── Presets ──────────────────────────

@router.get("/presets/list")
async def list_presets():
    return JSONResponse({
        'presets': get_available_presets(),
        'current': shared.settings.get('preset', ''),
    })


@router.get("/presets/{name}")
async def get_preset(name: str):
    try:
        from modules.presets import load_preset
        preset = load_preset(name)
        return JSONResponse(preset)
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=404)


@router.post("/presets/load")
async def load_preset_endpoint(request: Request):
    data = await request.json()
    name = data.get('name')
    if not name:
        return JSONResponse({'error': 'name required'}, status_code=400)

    try:
        from modules.presets import load_preset
        preset = load_preset(name)
        shared.settings.update(preset)
        shared.settings['preset'] = name
        return JSONResponse({'status': 'ok', 'preset': preset})
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=404)


@router.post("/presets/save")
async def save_preset(request: Request):
    data = await request.json()
    name = data.get('name', '').strip()
    if not name:
        return JSONResponse({'error': 'name required'}, status_code=400)

    from modules.utils import sanitize_filename, save_file
    from modules.presets import default_preset_values

    name = sanitize_filename(name)
    preset_data = {}
    for key in default_preset_values:
        if key in data:
            preset_data[key] = data[key]

    filepath = str(shared.user_data_dir / 'presets' / f'{name}.yaml')
    save_file(filepath, yaml.dump(preset_data, sort_keys=False, allow_unicode=True))
    return JSONResponse({'status': 'ok'})


# ─────────────────────────── Extensions ───────────────────────

@router.get("/extensions/list")
async def list_extensions():
    import modules.extensions as extensions_module
    active = shared.args.extensions or []
    return JSONResponse({
        'available': get_available_extensions(),
        'active': active,
    })


@router.post("/extensions/toggle")
async def toggle_extension(request: Request):
    data = await request.json()
    name = data.get('name')
    enable = data.get('enable', True)

    if not name:
        return JSONResponse({'error': 'name required'}, status_code=400)

    if shared.args.extensions is None:
        shared.args.extensions = []

    if enable and name not in shared.args.extensions:
        shared.args.extensions.append(name)
    elif not enable and name in shared.args.extensions:
        shared.args.extensions.remove(name)

    return JSONResponse({'status': 'ok', 'active': shared.args.extensions})


# ─────────────────────────── LoRA ─────────────────────────────

@router.get("/loras/list")
async def list_loras():
    return JSONResponse({
        'loras': get_available_loras(),
        'active': shared.lora_names,
    })


@router.post("/loras/load")
async def load_lora(request: Request):
    data = await request.json()
    names = data.get('names', [])
    try:
        from modules.LoRA import add_lora_to_model
        add_lora_to_model(names)
        return JSONResponse({'status': 'ok', 'active': shared.lora_names})
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)


# ─────────────────────────── Templates ────────────────────────

@router.get("/templates/list")
async def list_templates():
    return JSONResponse({
        'templates': get_available_instruction_templates(),
    })


@router.get("/templates/{name}")
async def get_template(name: str):
    try:
        filepath = shared.user_data_dir / 'instruction-templates' / f'{name}.yaml'
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f.read())
            return JSONResponse(data)
        return JSONResponse({'error': 'not found'}, status_code=404)
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=404)


# ─────────────────────────── Grammars ─────────────────────────

@router.get("/grammars/list")
async def list_grammars():
    return JSONResponse({'grammars': get_available_grammars()})


@router.get("/grammars/{name}")
async def get_grammar(name: str):
    try:
        filepath = shared.user_data_dir / 'grammars' / name
        if filepath.exists():
            return JSONResponse({'content': filepath.read_text(encoding='utf-8')})
        return JSONResponse({'error': 'not found'}, status_code=404)
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=404)


# ─────────────────────────── Prompts ──────────────────────────

@router.get("/prompts/list")
async def list_prompts():
    return JSONResponse({'prompts': get_available_prompts()})


@router.get("/prompts/{name}")
async def get_prompt(name: str):
    try:
        from modules.prompts import load_prompt
        text = load_prompt(name)
        return JSONResponse({'text': text})
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=404)


# ─────────────────────────── Misc Lists ───────────────────────

@router.get("/chat-styles/list")
async def list_chat_styles():
    return JSONResponse({'styles': get_available_chat_styles()})


@router.get("/users/list")
async def list_users():
    return JSONResponse({'users': get_available_users()})


@router.get("/image-models/list")
async def list_image_models():
    return JSONResponse({
        'models': get_available_image_models(),
        'current': shared.image_model_name,
    })


@router.get("/mmproj/list")
async def list_mmproj():
    return JSONResponse({'mmproj': get_available_mmproj()})


# ─────────────────────────── Loaders ──────────────────────────

@router.get("/loaders/list")
async def list_loaders():
    from modules.loaders import loaders_and_params
    return JSONResponse({
        'loaders': list(loaders_and_params.keys()),
        'current': getattr(shared.args, 'loader', None),
    })


@router.get("/loaders/{name}/params")
async def get_loader_params(name: str):
    from modules.loaders import loaders_and_params
    if name in loaders_and_params:
        return JSONResponse({'params': list(loaders_and_params[name])})
    return JSONResponse({'error': 'loader not found'}, status_code=404)


# ─────────────────── WebSocket: Chat Generation ──────────────

@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get('action', 'send')
            params = data.get('params', {})
            text = data.get('text', '')

            state = _build_state(params)

            # Load history if unique_id provided
            if params.get('unique_id'):
                from modules.chat import load_history
                character = state.get('character_menu', state.get('character', 'Assistant'))
                mode = state.get('mode', 'instruct')
                state['history'] = load_history(params['unique_id'], character, mode)

            shared.stop_everything = False

            try:
                if action == 'send':
                    from modules.chat import generate_chat_reply, save_history
                    for history in generate_chat_reply(text, state, loading_message=False):
                        visible = history.get('visible', [])
                        last_reply = visible[-1][1] if visible else ''
                        await websocket.send_json({
                            'type': 'stream',
                            'text': last_reply,
                            'history': history,
                        })

                    # Save history
                    if not shared.args.multi_user and params.get('unique_id'):
                        save_history(history, params['unique_id'], character, mode)

                    await websocket.send_json({'type': 'done', 'history': history})

                elif action == 'regenerate':
                    from modules.chat import generate_chat_reply, save_history
                    for history in generate_chat_reply('', state, regenerate=True, loading_message=False):
                        visible = history.get('visible', [])
                        last_reply = visible[-1][1] if visible else ''
                        await websocket.send_json({
                            'type': 'stream',
                            'text': last_reply,
                            'history': history,
                        })

                    if not shared.args.multi_user and params.get('unique_id'):
                        save_history(history, params['unique_id'], character, mode)

                    await websocket.send_json({'type': 'done', 'history': history})

                elif action == 'continue':
                    from modules.chat import generate_chat_reply, save_history
                    for history in generate_chat_reply('', state, _continue=True, loading_message=False):
                        visible = history.get('visible', [])
                        last_reply = visible[-1][1] if visible else ''
                        await websocket.send_json({
                            'type': 'stream',
                            'text': last_reply,
                            'history': history,
                        })

                    if not shared.args.multi_user and params.get('unique_id'):
                        save_history(history, params['unique_id'], character, mode)

                    await websocket.send_json({'type': 'done', 'history': history})

                elif action == 'impersonate':
                    from modules.chat import generate_chat_prompt
                    from modules.text_generation import generate_reply

                    prompt = generate_chat_prompt('', state, impersonate=True)
                    stopping_strings = _get_stopping_strings(state)
                    reply_text = ''
                    for reply in generate_reply(prompt, state, stopping_strings=stopping_strings, is_chat=True):
                        reply_text = reply.lstrip(' ')
                        await websocket.send_json({
                            'type': 'stream',
                            'text': reply_text,
                        })

                    await websocket.send_json({'type': 'done', 'text': reply_text})

                elif action == 'stop':
                    shared.stop_everything = True
                    await websocket.send_json({'type': 'stopped'})

            except Exception as e:
                logger.exception("WebSocket chat error")
                await websocket.send_json({'type': 'error', 'error': str(e)})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("WebSocket connection error")


# ─────────────── WebSocket: Notebook Generation ──────────────

@router.websocket("/ws/notebook")
async def ws_notebook(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get('action', 'generate')
            params = data.get('params', {})
            text = data.get('text', '')

            state = _build_state(params)
            shared.stop_everything = False

            try:
                from modules.text_generation import generate_reply

                if action == 'generate':
                    full_reply = text if not shared.is_seq2seq else ''
                    for reply in generate_reply(text, state, is_chat=False, escape_html=True):
                        if not shared.is_seq2seq:
                            full_reply = text + reply
                        else:
                            full_reply = reply

                        await websocket.send_json({
                            'type': 'stream',
                            'text': full_reply,
                        })

                    await websocket.send_json({'type': 'done', 'text': full_reply})

                elif action == 'stop':
                    shared.stop_everything = True
                    await websocket.send_json({'type': 'stopped'})

            except Exception as e:
                logger.exception("WebSocket notebook error")
                await websocket.send_json({'type': 'error', 'error': str(e)})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("WebSocket connection error")


def _get_stopping_strings(state):
    """Extract stopping strings from state."""
    from modules.chat import get_stopping_strings
    return get_stopping_strings(state)


# ─────────────────────── Image Generation ─────────────────────

@router.post("/images/generate")
async def generate_image(request: Request):
    data = await request.json()
    try:
        from modules.image_models import generate_image as gen_img

        prompt = data.get('prompt', '')
        neg_prompt = data.get('negative_prompt', '')
        width = data.get('width', 1024)
        height = data.get('height', 1024)
        steps = data.get('steps', 9)
        cfg_scale = data.get('cfg_scale', 0.0)
        seed = data.get('seed', -1)

        if shared.image_model is None:
            return JSONResponse({'error': 'No image model loaded'}, status_code=400)

        images = gen_img(
            shared.image_model,
            prompt,
            negative_prompt=neg_prompt,
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=cfg_scale,
            seed=seed,
        )

        # Return image paths
        import base64
        from io import BytesIO
        results = []
        for img in images:
            buf = BytesIO()
            img.save(buf, format='PNG')
            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
            results.append(f"data:image/png;base64,{b64}")

        return JSONResponse({'images': results})
    except Exception as e:
        logger.exception("Image generation error")
        return JSONResponse({'error': str(e)}, status_code=500)


@router.post("/images/load-model")
async def load_image_model_endpoint(request: Request):
    data = await request.json()
    model_name = data.get('model_name')
    if not model_name:
        return JSONResponse({'error': 'model_name required'}, status_code=400)

    try:
        from modules.image_models import load_image_model
        result = load_image_model(
            model_name,
            dtype=data.get('dtype', 'bfloat16'),
            attn_backend=data.get('attn_backend', 'sdpa'),
            cpu_offload=data.get('cpu_offload', False),
            compile_model=data.get('compile', False),
            quant_method=data.get('quant', 'none'),
        )
        if result is not None:
            shared.image_model_name = model_name
            return JSONResponse({'status': 'ok', 'model': model_name})
        else:
            return JSONResponse({'error': 'Failed to load image model'}, status_code=500)
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)


# ─────────────────────── Token Count ──────────────────────────

@router.post("/tokens/count")
async def count_tokens(request: Request):
    data = await request.json()
    text = data.get('text', '')

    if shared.tokenizer is None:
        return JSONResponse({'count': len(text.split())})

    try:
        from modules.text_generation import get_encoded_length
        count = get_encoded_length(text)
        return JSONResponse({'count': count})
    except Exception:
        return JSONResponse({'count': len(text.split())})
