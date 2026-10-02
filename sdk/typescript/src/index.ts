export { PrometheaClient, type PrometheaClientOptions } from './client.js'
export { PrometheaError } from './errors.js'
export { type TaskListOptions } from './tasks.js'
export { type FileUploadOptions } from './files.js'
export { type WorkbenchQuery, type WorkbenchWatchOptions } from './workbench.js'
export { CognitionClient } from './cognition.js'
export { CanvasClient } from './canvas.js'
export type {
  Attachment,
  UserFile,
  FileUploadResponse,
  Error as ErrorDetail,
  Event,
  RunRequest,
  RunResponse,
  Session,
  ToolCall,
  ToolResult,
  Task,
  TaskRun,
  TaskControlRequest,
  TaskStartRunRequest,
  TaskCancelRequest,
  TaskResponse,
  TaskListResponse,
  TaskRunResponse,
  WorkbenchScope,
  WorkbenchActivity,
  WorkbenchWaitingAction,
  WorkbenchSnapshot,
  CognitionItem,
  CognitionBundle,
  CognitionResponse,
  CanvasEnvironment,
  CanvasEnvironmentList,
} from './generated/public-contracts.js'
