#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{
    CustomMenuItem, Manager, SystemTray, SystemTrayEvent, SystemTrayMenu, SystemTrayMenuItem,
    Window,
};

/// 应用状态，管理Python服务进程
struct AppState {
    python_server: Mutex<Option<Child>>,
}

/// 启动Python FastAPI服务
fn start_python_server() -> Result<Child, std::io::Error> {
    #[cfg(target_os = "windows")]
    let python_cmd = "python";
    
    #[cfg(not(target_os = "windows"))]
    let python_cmd = "python3";

    println!("正在启动 Python 服务...");
    
    let child = Command::new(python_cmd)
        .args(&["-m", "uvicorn", "api_server.server:app", "--host", "127.0.0.1", "--port", "8000"])
        .spawn()?;
    
    println!("Python 服务已启动，PID: {}", child.id());
    
    // 等待服务启动
    std::thread::sleep(std::time::Duration::from_secs(2));
    
    Ok(child)
}

/// 停止Python服务
fn stop_python_server(child: &mut Child) {
    println!("正在停止 Python 服务...");
    let _ = child.kill();
    println!("Python 服务已停止");
}

/// 创建系统托盘
fn create_system_tray() -> SystemTray {
    let open = CustomMenuItem::new("open".to_string(), "打开主窗口");
    let hide = CustomMenuItem::new("hide".to_string(), "隐藏窗口");
    let quit = CustomMenuItem::new("quit".to_string(), "退出 Promethea");
    
    let tray_menu = SystemTrayMenu::new()
        .add_item(open)
        .add_item(hide)
        .add_native_item(SystemTrayMenuItem::Separator)
        .add_item(quit);
    
    SystemTray::new().with_menu(tray_menu)
}

/// 处理系统托盘事件
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
                    // 清理Python服务
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

/// 处理窗口关闭事件
fn handle_window_close_event(window: &Window) {
    // 点击关闭按钮时隐藏窗口而不是退出
    window.hide().unwrap();
}

fn main() {
    // 启动Python服务
    let python_server = match start_python_server() {
        Ok(child) => Some(child),
        Err(e) => {
            eprintln!("启动 Python 服务失败: {}", e);
            eprintln!("请确保：");
            eprintln!("1. 已安装 Python 3.8+");
            eprintln!("2. 已安装依赖: pip install -r api_server/requirements.txt");
            eprintln!("3. 在项目根目录运行此程序");
            std::process::exit(1);
        }
    };

    let app_state = AppState {
        python_server: Mutex::new(python_server),
    };

    // 创建系统托盘
    let tray = create_system_tray();

    // 构建Tauri应用
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
        .setup(|app| {
            // 应用启动时的初始化
            println!("Promethea Agent 已启动");
            println!("Web界面地址: http://127.0.0.1:8000");
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("启动 Tauri 应用失败");
}

