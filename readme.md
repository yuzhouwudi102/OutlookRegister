# OutlookRegister  

自动读取备用邮箱验证码：
1. 将备用邮箱写入 `Results/backup_email.txt`，每行格式为 `邮箱: 密码`，可填写多个邮箱。
2. 运行 `python authorize_recovery_mailbox.py`。程序会比较备用邮箱列表与 `Results/recovery_mailbox_token` 中的令牌，并依次授权尚未授权的邮箱。
3. 每个备用邮箱的 OAuth 令牌会单独保存在 `Results/recovery_mailbox_token` 文件夹中。
4. 注册遇到备用邮箱页面时，程序会从已授权邮箱中随机选择一个，读取验证码并自动提交。
5. `Results/unlogged_email.txt` 只保存关闭新邮箱 OAuth 时注册成功的邮箱，不再用于备用邮箱。
6. `oauth2.enable_oauth2=false` 只关闭新注册邮箱的令牌获取；备用邮箱填写和自动取码流程仍会继续执行，账号密码会立即写入 `Results/unlogged_email.txt`。
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
