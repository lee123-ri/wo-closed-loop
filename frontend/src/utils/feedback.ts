import { MessagePlugin } from "tdesign-vue-next/es/message";
import { DialogPlugin } from "tdesign-vue-next/es/dialog";

/** 统一轻提示（替代原生 alert） */
export const toast = {
  success: (msg: string) => MessagePlugin.success(msg),
  warning: (msg: string) => MessagePlugin.warning(msg),
  error: (msg: string) => MessagePlugin.error(msg),
};

/** 统一确认弹窗（替代原生 confirm），resolve(true)=确认 / false=取消 */
export function confirmDialog(message: string, title = "确认"): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v: boolean) => {
      if (!settled) {
        settled = true;
        resolve(v);
      }
    };
    const dlg = DialogPlugin.confirm({
      header: title,
      body: message,
      onConfirm: () => {
        done(true);
        dlg.destroy();
      },
      onCancel: () => {
        done(false);
        dlg.destroy();
      },
      onClose: () => done(false),
    });
  });
}