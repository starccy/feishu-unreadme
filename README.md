# feishu-unreadme


在 js 端屏蔽飞书消息的已读回执。即，自己在看到其他人发送的（私聊或群聊）普通消息后，
对方的视角也会保持在自己未读的状态。


## 使用方法

先确保飞书进程已经关闭，避免脚本执行时因文件占用导致报错。

终端下执行：

```bash
python main.py <飞书安装根目录>
```

脚本会解压 `webcontent/messenger.asar` 文件并修改里面的 js 文件。

修改成功后请重启飞书客户端。若发现飞书功能异常，请将脚本生成的 `messenger.asar` 目录删除，
并将 `messenger.asar.bak` 文件重命名回 `messenger.asar`.


## 原理

飞书客户端前端 js 会监听 DOM 事件并尝试收集新消息的 messageId, 之后传给
native 层发送网络请求给服务器。所以在传给 native 之前把要传的消息列表 id
清空就好了。


## 已知问题 / TODO

毕竟只是在 js 层修改的逻辑，而非拦截网络请求等更加靠谱的方式。前端可能有多个入口
来进行消息已读回执的请求，导致在以下情况下对方会看到自己已读：

* 对一个消息进行引用并回复
* 对一个消息贴表情
* 接收对方发送的文件

此外要注意，飞书更新后会覆盖修改的文件，所以需要重新执行脚本来修改。
