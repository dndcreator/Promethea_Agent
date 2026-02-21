#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{
    CustomMenuItem, Manager, SystemTray, SystemTrayEvent, SystemTrayMenu, SystemTrayMenuItem,
    Window,
};

struct AppState {
    python_server: Mutex<Option<Child>>,
}

fn start_python_server() -> Result<Child, std::io::Error> {
    #[cfg(target_os = "windows")]
    let python_cmd = "python";

    #[cfg(not(target_os = "windows"))]
    let python_cmd = "python3";

    println!("Starting Python service...");

    let child = Command::new(python_cmd)
        .args(&[
            "-m",
            "uvicorn",
            "gateway.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ])
        .spawn()?;

    println!("Python service started, PID: {}", child.id());
    std::thread::sleep(std::time::Duration::from_secs(2));
    Ok(child)
}

fn stop_python_server(child: &mut Child) {
    println!("Stopping Python service...");
    let _ = child.kill();
    println!("Python service stopped");
}

fn create_system_tray() -> SystemTray {
    let open = CustomMenuItem::new("open".to_string(), "Open");
    let hide = CustomMenuItem::new("hide".to_string(), "Hide");
    let quit = CustomMenuItem::new("quit".to_string(), "Quit Promethea");

    let tray_menu = SystemTrayMenu::new()
        .add_item(open)
        .add_item(hide)
        .add_native_item(SystemTrayMenuItem::Separator)
        .add_item(quit);

    SystemTray::new().with_menu(tray_menu)
}

fn handle_system_tray_event(app: &tauri::AppHandle, event: SystemTrayEvent) {
    match event {
        SystemTrayEvent::MenuItemClick { id, .. } => {
            let window = app.get_window("main").unwrap();
            match id.as_str() {
                "open" => {
                    window.show().unwrap();
                    window.set_focus().unwrap();
                }
                "hide" => {
                    window.hide().unwrap();
                }
                "quit" => {
                    if let Some(state) = app.try_state::<AppState>() {
                        if let Ok(mut server) = state.python_server.lock() {
                            if let Some(child) = server.as_mut() {
                                stop_python_server(child);
                            }
                        }
                    }
                    std::process::exit(0);
                }
                _ => {}
            }
        }
        SystemTrayEvent::DoubleClick { .. } => {
            let window = app.get_window("main").unwrap();
            window.show().unwrap();
            window.set_focus().unwrap();
        }
        _ => {}
    }
}

fn handle_window_close_event(window: &Window) {
    window.hide().unwrap();
}

fn main() {
    let python_server = match start_python_server() {
        Ok(child) => Some(child),
        Err(e) => {
            eprintln!("Failed to start Python service: {}", e);
            eprintln!("Please ensure:");
            eprintln!("1. Python 3.8+ is installed");
            eprintln!("2. Dependencies are installed: pip install -r requirements.txt");
            eprintln!("3. Run this app from project root");
            std::process::exit(1);
        }
    };

    let app_state = AppState {
        python_server: Mutex::new(python_server),
    };

    let tray = create_system_tray();

    tauri::Builder::default()
        .manage(app_state)
        .system_tray(tray)
        .on_system_tray_event(handle_system_tray_event)
        .on_window_event(|event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event.event() {
                event.window().hide().unwrap();
                api.prevent_close();
            }
        })
        .setup(|_app| {
            println!("Promethea Agent started");
            println!("Web UI: http://127.0.0.1:8000");
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("Failed to launch Tauri app");
}

