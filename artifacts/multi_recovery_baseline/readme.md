# OutlookRegister  

自动读取备用邮箱验证码：
1. `config.json` 中设置 `recovery_email`，并将 `recovery_mailbox.auto_fetch` 保持为 `true`。
2. 默认从 `Results/unlogged_email.txt` 读取备用邮箱密码，格式为 `邮箱: 密码`；也可以用环境变量 `OUTLOOK_RECOVERY_PASSWORD` 覆盖。
3. 首次运行会用备用邮箱完成 OAuth 授权，令牌缓存到 `Results/recovery_mailbox_token.json`，之后通过 Microsoft Graph 轮询新邮件。
4. 验证码提取成功后会自动填写验证码并点击提交；轮询超时和授权失败会让当前注册任务失败。
Outlook 注册机  
选择器经常更新，不保证时效性，自行测试。 

- 模拟人类填表操作  
- 自动过验证码  
- 注册成功  

设置相关：  
1.playwright使用性较差,如果使用playwright，则需要自行寻找指纹浏览器并填写绝对路径。  
2.如果使用patchright,且不需要Oauth2，则只需要更改代理地址.  
3.`Bot_protection_wait`单位为秒。  
4.`client_id`与`redirect_url`可以前往[Azure](https://azure.microsoft.com/zh-cn?OCID=cmmyhidqdn5_brandzone__EFID__)注册获取，不需要Oauth2可留空。  
5.`client_id`与`redirect_url`格式通常类似于`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`和`http://localhost:8000`。  
6.`Scopes`按照申请的权限填，不需要Oauth2可留空。  

使用教程：  
1.使用本地代理IP**搭建代理池**，在`config.json`填写你的代理地址。  
2.在设置中调整并发与最大注册量。  
3.如果你需要Oauth2，请在`config.json`中修改`"enable_oauth2"`的值为`true`并填写`Scopes`、`client_id`与`redirect_url`。  
4.安装相关依赖`pip install -r requirements.txt`，如果未安装相关浏览器，使用`patchright install chromium`。  
5.视运行脚本填写或留空`browser_path`。  
6.`python main.py`。  

注意事项：  
**IP**与成功率高度正相关，同一IP短时间不宜多次注册。
邮箱自动存储到工作目录的`Results`下。  
