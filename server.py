"""
Text Generation Web UI - System Shock 2 Edition
Main server entry point using FastAPI.
"""

import os
import signal
import sys
import time
import warnings
from pathlib import Path
from threading import Lock, Thread

# Install gradio shim before any module tries to import gradio
from modules.gradio_shim import install_shim as _install_gradio_shim
_install_gradio_shim()

import yaml

from modules import shared, utils
from modules.image_models import load_image_model
from modules.logging_colors import logger
from modules.prompts import load_prompt

import modules.extensions as extensions_module
from modules.LoRA import add_lora_to_model
from modules.models import load_model, unload_model_if_idle
from modules.models_settings import (
    get_fallback_settings,
    get_model_metadata,
    update_model_parameters
)
from modules.shared import do_cmd_flags_warnings

os.environ['BITSANDBYTES_NOWELCOME'] = '1'

warnings.filterwarnings('ignore', category=UserWarning, message='TypedStorage is deprecated')
warnings.filterwarnings('ignore', category=UserWarning, message='Using the update method is deprecated')
warnings.filterwarnings('ignore', category=UserWarning, message='Field "model_name" has conflict')
warnings.filterwarnings('ignore', category=UserWarning, message='Field "model_names" has conflict')


def signal_handler(sig, frame):
    # On second Ctrl+C, force an immediate exit
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)

    logger.info("Received Ctrl+C. Shutting down Text Generation Web UI gracefully.")

    # Explicitly stop LlamaServer to avoid __del__ cleanup issues during shutdown
    if shared.model and shared.model.__class__.__name__ == 'LlamaServer':
        try:
            shared.model.stop()
        except Exception:
            pass

    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def create_interface():
    """Create and launch the FastAPI web interface."""
    import uvicorn
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse
    from modules.web_routes import router

    app = FastAPI(title="Text Generation Web UI - System Shock 2 Edition")

    # Mount static files
    base_dir = Path(__file__).resolve().parent
    app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")

    # Include API routes
    app.include_router(router)

    # Import the extensions and execute their setup() functions
    if shared.args.extensions is not None and len(shared.args.extensions) > 0:
        extensions_module.load_extensions()

    # Start the API server if enabled
    if shared.args.api or shared.args.public_api:
        from modules.api.script import setup as api_setup
        api_setup()

    # Force some events to be triggered on page load
    shared.persistent_interface_state.update({
        'mode': shared.settings['mode'],
        'loader': shared.args.loader or 'llama.cpp',
    })

    if not shared.settings['prompt-notebook']:
        shared.settings['prompt-notebook'] = utils.get_available_prompts()[0]

    prompt = load_prompt(shared.settings['prompt-notebook'])
    shared.persistent_interface_state.update({
        'textbox-default': prompt,
        'textbox-notebook': prompt
    })

    # Regenerate character picture for default character
    if shared.settings['mode'] != 'instruct':
        from modules.chat import generate_pfp_cache
        generate_pfp_cache(shared.settings.get('character', 'Assistant'))

    # Serve the main page
    @app.get("/", response_class=HTMLResponse)
    async def root():
        template_path = base_dir / "templates" / "index.html"
        with open(template_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)

    # Determine host and port
    host = '0.0.0.0' if shared.args.listen else '127.0.0.1'
    if shared.args.listen_host:
        host = shared.args.listen_host
    port = shared.args.listen_port or 7860

    ssl_keyfile = shared.args.ssl_keyfile
    ssl_certfile = shared.args.ssl_certfile

    logger.info(f"Starting System Shock 2 UI on http{'s' if ssl_certfile else ''}://{host}:{port}")

    if shared.args.auto_launch:
        import webbrowser
        webbrowser.open(f"http{'s' if ssl_certfile else ''}://{'localhost' if host == '0.0.0.0' else host}:{port}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
        log_level="warning",
    )


if __name__ == "__main__":

    logger.info("Starting Text Generation Web UI")
    do_cmd_flags_warnings()

    # Load custom settings
    settings_file = None
    if shared.args.settings is not None and Path(shared.args.settings).exists():
        settings_file = Path(shared.args.settings)
    elif (shared.user_data_dir / 'settings.yaml').exists():
        settings_file = shared.user_data_dir / 'settings.yaml'

    if settings_file is not None:
        logger.info(f"Loading settings from \"{settings_file}\"")
        with open(settings_file, 'r', encoding='utf-8') as f:
            new_settings = yaml.safe_load(f.read())

        if new_settings:
            shared.settings.update(new_settings)

    # Apply CLI overrides for image model settings (CLI flags take precedence over saved settings)
    shared.apply_image_model_cli_overrides()

    # Fallback settings for models
    shared.model_config['.*'] = get_fallback_settings()
    shared.model_config.move_to_end('.*', last=False)  # Move to the beginning

    # Activate the extensions listed on settings.yaml
    extensions_module.available_extensions = utils.get_available_extensions()
    for extension in shared.settings['default_extensions']:
        # The openai extension was moved to modules/api and is now
        # activated with --api. Treat it as an alias for backwards compat.
        if extension == 'openai':
            shared.args.api = True
            continue

        shared.args.extensions = shared.args.extensions or []
        if extension not in shared.args.extensions:
            shared.args.extensions.append(extension)

    # Handle --extensions openai from the command line (moved to modules/api)
    if shared.args.extensions and 'openai' in shared.args.extensions:
        shared.args.extensions.remove('openai')
        shared.args.api = True

    # Load image model if specified via CLI
    if shared.args.image_model:
        logger.info(f"Loading image model: {shared.args.image_model}")
        result = load_image_model(
            shared.args.image_model,
            dtype=shared.settings.get('image_dtype', 'bfloat16'),
            attn_backend=shared.settings.get('image_attn_backend', 'sdpa'),
            cpu_offload=shared.settings.get('image_cpu_offload', False),
            compile_model=shared.settings.get('image_compile', False),
            quant_method=shared.settings.get('image_quant', 'none')
        )
        if result is not None:
            shared.image_model_name = shared.args.image_model
        else:
            logger.error(f"Failed to load image model: {shared.args.image_model}")

    available_models = utils.get_available_models()

    # Model defined through --model
    if shared.args.model is not None:
        shared.model_name = shared.args.model

    # Select the model from a command-line menu
    elif shared.args.model_menu:
        if len(available_models) == 0:
            logger.error('No models are available! Please download at least one.')
            sys.exit(0)
        else:
            print('The following models are available:\n')
            for i, model in enumerate(available_models):
                print(f'{i+1}. {model}')

            print(f'\nWhich one do you want to load? 1-{len(available_models)}\n')
            i = int(input()) - 1
            print()

        shared.model_name = available_models[i]

    # If any model has been selected, load it
    if shared.model_name != 'None':
        model_settings = get_model_metadata(shared.model_name)
        update_model_parameters(model_settings, initial=True)  # hijack the command-line arguments

        # Load the model
        shared.model, shared.tokenizer = load_model(shared.model_name)
        if shared.args.lora:
            add_lora_to_model(shared.args.lora)

    shared.generation_lock = Lock()

    if shared.args.idle_timeout > 0:
        timer_thread = Thread(target=unload_model_if_idle)
        timer_thread.daemon = True
        timer_thread.start()

    if shared.args.nowebui:
        # Start the API in standalone mode
        shared.args.extensions = [x for x in (shared.args.extensions or []) if x != 'gallery']
        if shared.args.extensions:
            extensions_module.load_extensions()

        if shared.args.api or shared.args.public_api:
            from modules.api.script import setup as api_setup
            api_setup()
    else:
        # Launch the web UI
        create_interface()
