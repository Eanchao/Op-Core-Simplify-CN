# 来源: https://github.com/corpnewt/SSDTTime/blob/7b3fb78112bf320a1bc6a7e50dddb2b375cb70b0/Scripts/run.py
# 中文翻译版本

import sys, subprocess, time, threading, shlex
try:
    from Queue import Queue, Empty
except:
    from queue import Queue, Empty

# 检查是否为POSIX系统（如Linux/macOS）
ON_POSIX = 'posix' in sys.builtin_module_names

class Run:
    
    def __init__(self):
        return

    def _read_output(self, pipe, q):
        """从管道读取输出并放入队列"""
        try:
            # 逐字符读取管道输出
            for line in iter(lambda: pipe.read(1), b''):
                q.put(line)
        except ValueError:
            pass
        finally:
            pipe.close()

    def _create_thread(self, output):
        """创建线程和队列来监视输出管道"""
        # 创建新的队列和线程对象来监视传入的输出管道
        q = Queue()
        t = threading.Thread(target=self._read_output, args=(output, q))
        t.daemon = True  # 设置为守护线程，主程序退出时自动结束
        return (q, t)

    def _stream_output(self, comm, shell=False):
        """流式执行命令并实时输出结果"""
        output = error = ""
        p = None
        try:
            # 处理命令格式
            if shell and type(comm) is list:
                comm = " ".join(shlex.quote(x) for x in comm)
            if not shell and type(comm) is str:
                comm = shlex.split(comm)
            
            # 启动子进程
            p = subprocess.Popen(
                comm, 
                shell=shell, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                bufsize=0, 
                universal_newlines=True, 
                close_fds=ON_POSIX
            )
            
            # 设置标准输出线程/队列
            q, t = self._create_thread(p.stdout)
            # 设置标准错误线程/队列
            qe, te = self._create_thread(p.stderr)
            
            # 启动两个线程
            t.start()
            te.start()

            while True:
                c = z = ""  # 存储从队列获取的字符
                
                # 尝试获取标准输出
                try:
                    c = q.get_nowait()
                except Empty:
                    pass
                else:
                    sys.stdout.write(c)
                    output += c
                    sys.stdout.flush()
                
                # 尝试获取标准错误
                try:
                    z = qe.get_nowait()
                except Empty:
                    pass
                else:
                    sys.stderr.write(z)
                    error += z
                    sys.stderr.flush()
                
                if not c == z == "":
                    continue  # 如果有输出，继续循环
                
                # 没有输出 - 检查进程是否仍在运行
                p.poll()
                if p.returncode is not None:
                    # 子进程已结束
                    break
                
                # 没有输出，但子进程仍在运行 - 等待20毫秒
                time.sleep(0.02)

            # 获取剩余输出
            o, e = p.communicate()
            return (output + o, error + e, p.returncode)
            
        except Exception as e:
            if p:
                try:
                    o, e = p.communicate()
                except:
                    o = e = ""
                return (output + o, error + e, p.returncode)
            return ("", "命令未找到！", 1)

    def _decode(self, value, encoding="utf-8", errors="ignore"):
        """仅当值为bytes类型时才进行解码"""
        if sys.version_info >= (3, 0) and isinstance(value, bytes):
            return value.decode(encoding, errors)
        return value

    def _run_command(self, comm, shell=False):
        """运行命令并返回输出，不实时显示"""
        c = None
        try:
            # 处理命令格式
            if shell and type(comm) is list:
                comm = " ".join(shlex.quote(x) for x in comm)
            if not shell and type(comm) is str:
                comm = shlex.split(comm)
            
            # 启动子进程
            p = subprocess.Popen(
                comm, 
                shell=shell, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE
            )
            
            # 获取输出
            c = p.communicate()
            
        except Exception as e:
            if c is None:
                return ("", "命令未找到！", 1)
        
        # 解码输出并返回
        return (self._decode(c[0]), self._decode(c[1]), p.returncode)

    def run(self, command_list, leave_on_fail=False):
        """运行命令列表
        
        参数:
            command_list: 命令列表，每个命令是一个字典
            leave_on_fail: 如果为True，遇到错误时停止执行
        
        返回:
            所有命令的输出列表，或单个命令的输出（如果只有一个命令）
        """
        # 命令列表应该是字典数组
        if type(command_list) is dict:
            # 只有一个命令
            command_list = [command_list]
            
        output_list = []
        
        for comm in command_list:
            args   = comm.get("args",   [])     # 命令参数
            shell  = comm.get("shell",  False)  # 是否使用shell执行
            stream = comm.get("stream", False)  # 是否实时流式输出
            sudo   = comm.get("sudo",   False)  # 是否使用sudo
            stdout = comm.get("stdout", False)  # 是否打印标准输出
            stderr = comm.get("stderr", False)  # 是否打印标准错误
            mess   = comm.get("message", None)  # 执行前显示的消息
            show   = comm.get("show",   False)  # 是否显示命令本身
            
            if mess is not None:
                print(mess)

            if not len(args):
                # 没有要处理的参数
                continue
                
            if sudo:
                # 检查是否有sudo
                out = self._run_command(["which", "sudo"])
                if "sudo" in out[0]:
                    # 可以使用sudo
                    if type(args) is list:
                        args.insert(0, out[0].replace("\n", ""))  # 添加到列表开头
                    elif type(args) is str:
                        args = out[0].replace("\n", "") + " " + args  # 添加到字符串开头
            
            if show:
                print(" ".join(args))

            if stream:
                # 实时流式输出
                out = self._stream_output(args, shell)
            else:
                # 运行并收集输出
                out = self._run_command(args, shell)
                if stdout and len(out[0]):
                    print(out[0])
                if stderr and len(out[1]):
                    print(out[1])
                    
            # 添加输出到列表
            output_list.append(out)
            
            # 检查错误
            if leave_on_fail and out[2] != 0:
                # 遇到错误 - 停止执行
                break
                
        if len(output_list) == 1:
            # 只运行了一个命令 - 直接返回该输出
            return output_list[0]
            
        return output_list