import gc
import os
import image
import nncase_runtime as nn
import ujson
import ulab.numpy as np
from libs.PipeLine import ScopedTiming
from media.display import *
from media.media import *
from media.sensor import *
import time
from machine import Pin, FPIOA, I2C

# ====================== OLED显示模块 ======================
HARD_I2C = False
OLED_I2C_ADDR = 0x3C

# 初始化I2C
if HARD_I2C:
    fpioa = FPIOA()
    fpioa.set_function(11, FPIOA.IIC2_SCL)
    fpioa.set_function(12, FPIOA.IIC2_SDA)
    i2c = I2C(2, freq=400 * 1000)
else:
    # 使用软件I2C
    i2c = I2C(5, scl=44, sda=45, freq=400 * 1000)


# 发送命令到SSD1306
def send_command(command):
    i2c.writeto(OLED_I2C_ADDR, bytearray([0x00, command]))


# 发送数据到SSD1306
def send_data(data):
    if isinstance(data, list):
        for d in data:
            i2c.writeto(OLED_I2C_ADDR, bytearray([0x40, d]))
    else:
        i2c.writeto(OLED_I2C_ADDR, bytearray([0x40, data]))


# SSD1306初始化序列
def oled_init():
    send_command(0xAE)  # Display OFF
    send_command(0xA8)  # Set MUX Ratio
    send_command(0x3F)  # 64MUX
    send_command(0xD3)  # Set display offset
    send_command(0x00)  # Offset = 0
    send_command(0x40)  # Set display start line to 0
    send_command(0xA1)  # Set segment re-map (normal)
    send_command(0xC0)  # Set COM output scan direction (normal)
    send_command(0xDA)  # Set COM pins hardware configuration
    send_command(0x12)  # Alternative COM pin config
    send_command(0x81)  # Set contrast control
    send_command(0x7F)  # Max contrast
    send_command(0xA4)  # Entire display ON
    send_command(0xA6)  # Set Normal display
    send_command(0xD5)  # Set oscillator frequency
    send_command(0x80)  # Frequency
    send_command(0x8D)  # Enable charge pump regulator
    send_command(0x14)  # Enable charge pump
    send_command(0xAF)  # Display ON


# 清空OLED屏幕
def oled_clear():
    for page in range(0, 8):  # 8 pages in 64px tall screen
        send_command(0xB0 + page)  # Set page start address
        send_command(0x00)  # Set low column address
        send_command(0x10)  # Set high column address
        # Clear 128 columns
        for _ in range(128):
            send_data(0x00)


# 扩展字模库
FONT_8x8 = {
    '0': [0x3E, 0x7F, 0x41, 0x41, 0x41, 0x41, 0x7F, 0x3E],
    '1': [0x00, 0x00, 0x21, 0x7F, 0x7F, 0x01, 0x00, 0x00],
    '2': [0x23, 0x67, 0x45, 0x49, 0x49, 0x71, 0x61, 0x00],
    '3': [0x22, 0x63, 0x49, 0x49, 0x49, 0x7F, 0x36, 0x00],
    '4': [0x0C, 0x1C, 0x34, 0x64, 0x7F, 0x7F, 0x04, 0x00],
    '5': [0x72, 0x73, 0x51, 0x51, 0x51, 0x5F, 0x4E, 0x00],
    '6': [0x3E, 0x7F, 0x49, 0x49, 0x49, 0x4F, 0x06, 0x00],
    '7': [0x40, 0x40, 0x47, 0x4F, 0x58, 0x70, 0x60, 0x00],
    '8': [0x36, 0x7F, 0x49, 0x49, 0x49, 0x7F, 0x36, 0x00],
    '9': [0x30, 0x79, 0x49, 0x49, 0x49, 0x7F, 0x3E, 0x00],
    ' ': [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
    ':': [0x00, 0x00, 0x14, 0x00, 0x00, 0x14, 0x00, 0x00],
    'A': [0x1F, 0x3F, 0x64, 0x44, 0x64, 0x3F, 0x1F, 0x00],
    'B': [0x7F, 0x7F, 0x49, 0x49, 0x49, 0x7F, 0x36, 0x00]
}


# 在OLED指定位置显示文本
def oled_show_text(text, page=0, start_col=0):
    for char in text:
        if char in FONT_8x8:
            # 设置页地址和列地址
            send_command(0xB0 | page)  # 设置页地址
            send_command(0x00 | (start_col & 0x0F))  # 低4位列地址
            send_command(0x10 | ((start_col >> 4) & 0x0F))  # 高4位列地址

            # 发送字符数据
            send_data(FONT_8x8[char])
            start_col += 8  # 每个字符占8列
        else:
            # 对于不在字库中的字符，显示空格
            send_command(0xB0 | page)
            send_command(0x00 | (start_col & 0x0F))
            send_command(0x10 | ((start_col >> 4) & 0x0F))
            send_data(FONT_8x8[' '])
            start_col += 8


# 更新OLED显示内容
def update_oled_display(value_A, value_B):
    oled_clear()
    oled_show_text(f"A : {value_A}", page=0, start_col=0)  # 第一行
    oled_show_text(f"B : {value_B}", page=1, start_col=0)  # 第二行


# ====================== 矩阵按键模块 ======================
# 设置矩阵按键引脚
fpioa = FPIOA()
fpioa.set_function(28, FPIOA.GPIO28)
fpioa.set_function(29, FPIOA.GPIO29)
fpioa.set_function(30, FPIOA.GPIO30)
fpioa.set_function(31, FPIOA.GPIO31)
fpioa.set_function(18, FPIOA.GPIO18)
fpioa.set_function(19, FPIOA.GPIO19)
fpioa.set_function(33, FPIOA.GPIO33)
fpioa.set_function(35, FPIOA.GPIO35)

# 创建行的对象
row1 = Pin(28, Pin.IN, Pin.PULL_DOWN)
row2 = Pin(29, Pin.IN, Pin.PULL_DOWN)
row3 = Pin(30, Pin.IN, Pin.PULL_DOWN)
row4 = Pin(31, Pin.IN, Pin.PULL_DOWN)
row_list = [row1, row2, row3, row4]

# 创建列的对象
col1 = Pin(18, Pin.OUT)
col2 = Pin(19, Pin.OUT)
col3 = Pin(33, Pin.OUT)
col4 = Pin(35, Pin.OUT)
col_list = [col1, col2, col3, col4]

# 键盘矩阵表
key_names = [
    ["1", "2", "3", "4"],
    ["5", "6", "7", "8"],
    ["9", "10", "11", "12"],
    ["13", "14", "15", "16"]
]

# 按键状态变量
last_key = None
key_pressed = False
key_debounce_time = 0


# 检测按键状态
def detect_key():
    global last_key, key_pressed, key_debounce_time

    current_key = None

    # 扫描按键矩阵
    for i, col in enumerate(col_list):
        # 关闭所有列
        for temp in col_list:
            temp.value(0)

        # 打开当前列
        col.value(1)
        time.sleep_ms(1)  # 短暂延时稳定信号

        # 检查所有行
        for j, row in enumerate(row_list):
            if row.value() == 1:
                current_key = key_names[j][i]
                break

        # 关闭当前列
        col.value(0)

        if current_key:
            break

    # 按键防抖处理
    if current_key:
        current_time = time.ticks_ms()
        if current_key == last_key:
            if current_time - key_debounce_time > 50 and not key_pressed:
                key_pressed = True
                key_debounce_time = current_time
                return current_key
        else:
            last_key = current_key
            key_debounce_time = current_time
    else:
        last_key = None
        key_pressed = False

    return None


# ====================== LED控制模块 ======================
# 设置LED引脚
fpioa.set_function(6, FPIOA.GPIO6)
fpioa.set_function(42, FPIOA.GPIO42)

# 创建LED对象
LED1 = Pin(42, Pin.OUT)
LED2 = Pin(6, Pin.OUT)


# 控制LED状态
def control_leds(class_id):
    if class_id == 0:  # class1
        LED1.on()  # LED1亮
        LED2.off()  # LED2灭
    elif class_id == 1:  # class2
        LED1.off()  # LED1灭
        LED2.on()  # LED2亮
    else:  # 其他情况
        LED1.off()  # LED1灭
        LED2.off()  # LED2灭


# ====================== 主函数 ======================
def main():
    print("智能识别系统启动")

    # 初始化OLED
    oled_init()
    oled_clear()
    time.sleep(0.5)  # 给OLED初始化时间

    # 初始化LED
    control_leds(-1)

    # 初始化变量
    value_A = 0
    value_B = 0
    update_oled_display(value_A, value_B)
    print("OLED初始化完成，显示初始值")

    # 图像分类参数
    display_mode = "lcd"
    if display_mode == "lcd":
        DISPLAY_WIDTH = ALIGN_UP(800, 16)
        DISPLAY_HEIGHT = 480
    else:
        DISPLAY_WIDTH = ALIGN_UP(1920, 16)
        DISPLAY_HEIGHT = 1080

    OUT_RGB888P_WIDTH = ALIGN_UP(640, 16)
    OUT_RGB888P_HEIGH = 360

    root_path = "/sdcard/mp_deployment_source/"
    config_path = root_path + "deploy_config.json"

    # 加载配置文件
    try:
        with open(config_path, "r") as json_file:
            deploy_conf = ujson.load(json_file)
        print("配置文件加载成功")
    except Exception as e:
        print(f"配置文件加载失败: {e}")
        return

    kmodel_name = deploy_conf["kmodel_path"]
    labels = deploy_conf["categories"]
    confidence_threshold = deploy_conf["confidence_threshold"]
    model_input_size = deploy_conf["img_size"]
    num_classes = deploy_conf["num_classes"]
    cls_idx = -1
    score = 0.0

    # 初始化kpu并加载模型
    kpu = nn.kpu()
    kpu.load_kmodel(root_path + kmodel_name)
    print("KPU模型加载成功")

    # 初始化ai2d用于预处理
    ai2d = nn.ai2d()
    ai2d.set_dtype(nn.ai2d_format.NCHW_FMT, nn.ai2d_format.NCHW_FMT, np.uint8, np.uint8)
    ai2d.set_resize_param(True, nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
    ai2d_builder = ai2d.build(
        [1, 3, OUT_RGB888P_HEIGH, OUT_RGB888P_WIDTH],
        [1, 3, model_input_size[1], model_input_size[0]]
    )

    # 初始化并配置sensor
    sensor = Sensor()
    sensor.reset()
    sensor.set_hmirror(False)
    sensor.set_vflip(False)
    sensor.set_framesize(width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT)
    sensor.set_pixformat(PIXEL_FORMAT_YUV_SEMIPLANAR_420)
    sensor.set_framesize(width=OUT_RGB888P_WIDTH, height=OUT_RGB888P_HEIGH, chn=CAM_CHN_ID_2)
    sensor.set_pixformat(PIXEL_FORMAT_RGB_888_PLANAR, chn=CAM_CHN_ID_2)

    # 绑定通道0的输出到vo
    sensor_bind_info = sensor.bind_info(x=0, y=0, chn=CAM_CHN_ID_0)
    Display.bind_layer(**sensor_bind_info, layer=Display.LAYER_VIDEO1)

    if display_mode == "lcd":
        Display.init(Display.ST7701, to_ide=True)
    else:
        Display.init(Display.LT9611, to_ide=True)

    # 创建OSD图像
    osd_img = image.Image(DISPLAY_WIDTH, DISPLAY_HEIGHT, image.ARGB8888)

    # media初始化
    MediaManager.init()

    # 启动sensor
    sensor.run()
    print("摄像头启动成功")

    # 初始化变量
    rgb888p_img = None
    ai2d_input_tensor = None
    data = np.ones((1, 3, model_input_size[1], model_input_size[0]), dtype=np.uint8)
    ai2d_output_tensor = nn.from_numpy(data)

    # 上一次识别的类别
    last_class = -1

    print("开始图像分类与系统控制...")
    try:
        while True:
            with ScopedTiming("total", 1):
                # 检测按键
                key = detect_key()
                if key:
                    print(f"按键 {key} 被按下")

                    # 根据当前识别类别处理按键
                    if cls_idx == 0:  # class1
                        if key == "1":
                            value_A += 1
                        elif key == "2":
                            value_A += 2
                        elif key == "3":
                            value_A += 3
                        elif key == "4":
                            value_A += 4
                        elif key == "5":
                            value_A += 5
                        elif key == "6":
                            value_A = 0
                        update_oled_display(value_A, value_B)
                        print(f"更新A值: {value_A}")

                    elif cls_idx == 1:  # class2
                        if key == "1":
                            value_B += 1
                        elif key == "2":
                            value_B += 2
                        elif key == "3":
                            value_B += 3
                        elif key == "4":
                            value_B += 4
                        elif key == "5":
                            value_B += 5
                        elif key == "6":
                            value_B = 0
                        update_oled_display(value_A, value_B)
                        print(f"更新B值: {value_B}")

                # 获取图像并进行分类
                rgb888p_img = sensor.snapshot(chn=CAM_CHN_ID_2)
                if rgb888p_img is not None and rgb888p_img.format() == image.RGBP888:
                    ai2d_input = rgb888p_img.to_numpy_ref()
                    ai2d_input_tensor = nn.from_numpy(ai2d_input)

                    # 预处理
                    ai2d_builder.run(ai2d_input_tensor, ai2d_output_tensor)

                    # 模型推理
                    kpu.set_input_tensor(0, ai2d_output_tensor)
                    kpu.run()

                    # 获取输出
                    results = []
                    for i in range(kpu.outputs_size()):
                        output_data = kpu.get_output_tensor(i)
                        result = output_data.to_numpy()
                        del output_data
                        results.append(result)

                    # 后处理
                    if num_classes > 2:
                        softmax_res = np.array(results[0][0])
                        exp_x = np.exp(softmax_res - np.max(softmax_res))
                        softmax_res = exp_x / np.sum(exp_x)
                        cls_idx = np.argmax(softmax_res)
                        if softmax_res[cls_idx] > confidence_threshold:
                            score = softmax_res[cls_idx]
                            print(f"分类结果: {labels[cls_idx]}, 置信度: {score:.4f}")
                        else:
                            cls_idx = -1
                            score = 0.0
                    else:
                        sigmoid_res = 1 / (1 + np.exp(-results[0][0][0]))
                        if sigmoid_res > confidence_threshold:
                            cls_idx = 1
                            score = sigmoid_res
                            print(f"分类结果: {labels[1]}, 置信度: {score:.4f}")
                        else:
                            cls_idx = 0
                            score = 1 - sigmoid_res
                            print(f"分类结果: {labels[0]}, 置信度: {score:.4f}")

                    # 控制LED状态
                    if cls_idx != last_class:
                        control_leds(cls_idx)
                        last_class = cls_idx
                        print(
                            f"LED状态更新: LED1 {'亮' if cls_idx == 0 else '灭'}, LED2 {'亮' if cls_idx == 1 else '灭'}")

                # 显示结果
                osd_img.clear()
                if cls_idx >= 0:
                    # 显示分类结果
                    osd_img.draw_string_advanced(
                        5, 5, 32, f"结果: {labels[cls_idx]} 置信度: {score:.3f}", color=(0, 255, 0)
                    )

                    # 显示当前LED状态
                    osd_img.draw_string_advanced(
                        5, 40, 28, f"LED1: {'亮' if cls_idx == 0 else '灭'}",
                        color=(255, 0, 0) if cls_idx == 0 else (100, 100, 100)
                    )
                    osd_img.draw_string_advanced(
                        5, 70, 28, f"LED2: {'亮' if cls_idx == 1 else '灭'}",
                        color=(0, 0, 255) if cls_idx == 1 else (100, 100, 100)
                    )

                    # 显示当前A和B的值
                    osd_img.draw_string_advanced(
                        5, 100, 28, f"A: {value_A}  B: {value_B}", color=(255, 255, 0)
                    )
                else:
                    osd_img.draw_string_advanced(
                        5, 5, 32, "未识别到有效目标", color=(255, 0, 0)
                    )

                Display.show_image(osd_img, 0, 0, Display.LAYER_OSD3)

                # 内存管理
                rgb888p_img = None
                gc.collect()

    except KeyboardInterrupt:
        print("程序被用户中断")
    except Exception as e:
        print(f"程序运行出错: {e}")
    finally:
        # 清理资源
        if 'ai2d_input_tensor' in locals():
            del ai2d_input_tensor
        if 'ai2d_output_tensor' in locals():
            del ai2d_output_tensor
        sensor.stop()
        Display.deinit()
        MediaManager.deinit()
        control_leds(-1)  # 关闭所有LED
        oled_clear()
        print("系统资源已清理，程序结束")


if __name__ == "__main__":
    main()

# 已更改：2025.10.22